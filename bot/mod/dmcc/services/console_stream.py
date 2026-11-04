"""bot/mod/dmcc/services/console_stream.py

Modification():

- Opt-in incremental Discord console feed from authenticated bounded log requests.
- Redact network addresses, passwords and tokens; never execute channel text.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import re

_LOGGER = logging.getLogger(__name__)
_IPV4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_IPV6 = re.compile(r"(?<![A-Za-z0-9])(?:[0-9A-Fa-f]{0,4}:){2,8}[0-9A-Fa-f]{0,4}(?![A-Za-z0-9])")
_SECRET = re.compile(r"(?i)\b(password|token|api[_-]?key|secret|authorization|session)\s*[:=]\s*\S+")
_BEARER = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+")
_MASS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_MAX_LINES = 80
_MAX_CHARS = 1850


def redact_console_line(line: str) -> str:
    """Conservatively remove addresses, credentials and ping syntax."""
    if not isinstance(line, str):
        return ""
    value = _IPV4.sub("[REDACTED]", line)
    value = _IPV6.sub("[REDACTED]", value)
    value = _BEARER.sub("Authorization=[REDACTED]", value)
    value = _SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
    value = _MASS.sub(lambda m: f"[{m.group(1).lower()}]", value)
    return value.replace("`", "'").replace("\r", " ").replace("\x00", "")[:_MAX_CHARS]


@dataclass(frozen=True, slots=True)
class ConsoleStreamConfig:
    enabled: bool = False
    poll_seconds: float = 5.0
    servers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: object, server_ids: set[str]) -> "ConsoleStreamConfig":
        if not isinstance(raw, Mapping) or set(raw) - {"enabled", "poll_seconds", "servers"}:
            raise ValueError("console_stream must be an object with documented options")
        enabled = raw.get("enabled", False)
        poll = raw.get("poll_seconds", 5)
        if type(enabled) is not bool:
            raise ValueError("console_stream.enabled must be a boolean")
        if isinstance(poll, bool) or not isinstance(poll, (float, int)) or not 2 <= poll <= 3600:
            raise ValueError("console_stream.poll_seconds must be 2..3600")
        servers = raw.get("servers", {})
        if not isinstance(servers, Mapping) or len(servers) > 16:
            raise ValueError("console_stream.servers must be an object of up to 16 servers")
        result: dict[str, str] = {}
        for server_id, entry in servers.items():
            if server_id not in server_ids or not isinstance(entry, Mapping) or set(entry) != {"channel_id"}:
                raise ValueError("invalid console_stream server configuration")
            channel = entry["channel_id"]
            if not isinstance(channel, str) or not channel.isascii() or not channel.isdecimal() or not 15 <= len(channel) <= 20:
                raise ValueError("console_stream channel_id must be a Discord ID")
            result[server_id] = channel
        return cls(enabled, float(poll), result)


class ConsoleStreamService:
    """Best-effort incremental log mirror; cannot execute server commands."""

    def __init__(self, config: ConsoleStreamConfig, bridge: object, manager: object, sender: object) -> None:
        self._config = config
        self._bridge = bridge
        self._manager = manager
        self._sender = sender
        self._last: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._config.enabled and self._task is None:
            self._task = asyncio.create_task(self._run(), name="dmcc-console-stream")

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                _LOGGER.exception("DMCC console stream cycle failed")
            await asyncio.sleep(self._config.poll_seconds)

    async def run_once(self) -> None:
        if not self._config.enabled:
            return
        for server_id, channel_id in self._config.servers.items():
            if self._manager.get(server_id) is None:
                self._last.pop(server_id, None)
                continue
            try:
                response = await asyncio.wait_for(self._bridge.log(server_id), timeout=8)
                raw = response.get("content") if isinstance(response, Mapping) else None
                if not isinstance(raw, str):
                    continue
                # The request protocol returns only the end of latest.log,
                # so never replay old startup logs into a newly enabled feed.
                if server_id not in self._last:
                    self._last[server_id] = raw
                    continue
                previous = self._last[server_id]
                if raw == previous:
                    continue
                fresh = self._delta(previous, raw)
                if not fresh:
                    self._last[server_id] = raw
                    continue
                lines = [redact_console_line(line) for line in fresh.splitlines()[-_MAX_LINES:]]
                cleaned = "\n".join(line for line in lines if line).strip()
                if cleaned:
                    if len(cleaned) > _MAX_CHARS:
                        cleaned = "[log truncated]\n" + cleaned[-(_MAX_CHARS - 16):]
                    await self._sender.send_discord_message(
                        channel_id, f"```text\n{cleaned}\n```",
                    )
                self._last[server_id] = raw
            except (ConnectionError, LookupError, TimeoutError, ValueError, OSError):
                _LOGGER.warning("DMCC console stream unavailable server_id=%s", server_id)
            except Exception:
                _LOGGER.exception("DMCC console stream failed server_id=%s", server_id)

    @staticmethod
    def _delta(previous: str, current: str) -> str:
        if current.startswith(previous):
            return current[len(previous):]
        if not previous:
            return current
        anchor = previous[-min(len(previous), 128):]
        offset = current.rfind(anchor)
        if offset != -1:
            return current[offset + len(anchor):]
        # Log rotation or a large overwrite: avoid replaying old content.
        return current[-_MAX_CHARS:]

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
