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
from pathlib import Path

from ..repositories.json_file import AtomicJsonFile

_LOGGER = logging.getLogger(__name__)
_IPV4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_IPV6 = re.compile(r"(?<![A-Za-z0-9])(?:[0-9A-Fa-f]{0,4}:){2,8}[0-9A-Fa-f]{0,4}(?![A-Za-z0-9])")
_SECRET = re.compile(r"(?i)\b(password|token|api[_-]?key|secret|authorization|session)\s*[:=]\s*\S+")
_BEARER = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+")
_MASS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
_PRIVATE_COMMAND = re.compile(
    r"(?i)(\bissued\s+(?:server\s+)?command\s*:\s*)/"
    r"(?:msg|tell|w|r|whisper|login|register|password|auth|dmcc|link|unlink)"
    r"(?=\s|$).*"
)

_MAX_LINES = 80
_MAX_CHARS = 1850


def _validate_cursors(raw: object) -> dict[str, dict[str, str | int]]:
    if not isinstance(raw, dict) or len(raw) > 32:
        raise ValueError("invalid DMCC cursor document")
    for server, entry in raw.items():
        if (
            not isinstance(server, str) or not server or len(server) > 128
            or not isinstance(entry, dict)
            or set(entry) != {"file_id", "next_offset"}
            or not isinstance(entry["file_id"], str)
            or not 1 <= len(entry["file_id"]) <= 64
            or not entry["file_id"].isascii()
            or type(entry["next_offset"]) is not int
            or not 0 <= entry["next_offset"] <= (2 ** 63 - 1)
        ):
            raise ValueError("invalid DMCC cursor entry")
    return raw


def redact_console_line(line: str) -> str:
    """Conservatively remove addresses, credentials and ping syntax."""
    if not isinstance(line, str):
        return ""
    value = _PRIVATE_COMMAND.sub(lambda match: match.group(1) + "[REDACTED]", line)
    value = _IPV4.sub("[REDACTED]", value)
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
    execute_from_channel: bool = False

    @classmethod
    def from_mapping(cls, raw: object, server_ids: set[str]) -> "ConsoleStreamConfig":
        if not isinstance(raw, Mapping) or set(raw) - {"enabled", "poll_seconds", "servers", "execute_from_channel"}:
            raise ValueError("console_stream must be an object with documented options")
        enabled = raw.get("enabled", False)
        execute = raw.get("execute_from_channel", False)
        if type(execute) is not bool:
            raise ValueError("console_stream.execute_from_channel must be boolean")
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
        return cls(enabled, float(poll), result, execute)


class ConsoleStreamService:
    """Best-effort incremental log mirror; cannot execute server commands."""

    def __init__(
        self, config: ConsoleStreamConfig, bridge: object, manager: object,
        sender: object, *, cursor_path: Path | None = None,
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._manager = manager
        self._sender = sender
        self._last: dict[str, str] = {}
        self._cursor_file = (
            AtomicJsonFile(cursor_path, _validate_cursors)
            if cursor_path is not None else None
        )
        self._cursors = self._cursor_file.read({}) if self._cursor_file is not None else {}
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
            if self._cursor_file is not None:
                await self._run_cursor_once(server_id, channel_id)
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

    async def _run_cursor_once(self, server_id: str, channel_id: str) -> None:
        """Commit the file cursor only after a successful Discord delivery."""
        previous = self._cursors.get(server_id)
        offset = previous["next_offset"] if previous else -1
        file_id = previous["file_id"] if previous else ""
        try:
            response = await asyncio.wait_for(
                self._bridge.log_chunk(server_id, offset, file_id),
                timeout=8,
            )
            if not isinstance(response, Mapping):
                raise ValueError("malformed cursor response")
            chunk = response.get("content")
            new_id = response.get("file_id")
            next_offset = response.get("next_offset")
            if (
                not isinstance(chunk, str) or len(chunk) > 4096
                or not isinstance(new_id, str) or not 1 <= len(new_id) <= 64
                or not new_id.isascii()
                or type(next_offset) is not int
                or not 0 <= next_offset <= (2 ** 63 - 1)
            ):
                raise ValueError("invalid cursor response fields")
            if offset != -1 and chunk:
                clean_lines = [
                    redact_console_line(line)
                    for line in chunk.splitlines()[-_MAX_LINES:]
                ]
                cleaned = "\n".join(line for line in clean_lines if line).strip()[:_MAX_CHARS]
                if cleaned:
                    text = f"```text\n{cleaned}\n```"
                    required = getattr(self._sender, "send_discord_message_required", None)
                    if callable(required):
                        await required(channel_id, text)
                    else:
                        await self._sender.send_discord_message(channel_id, text)
            updated = dict(self._cursors)
            updated[server_id] = {"file_id": new_id, "next_offset": next_offset}
            if self._cursor_file is None:
                return
            self._cursor_file.write(updated)
            self._cursors = updated
        except (ConnectionError, LookupError, TimeoutError, ValueError, OSError):
            _LOGGER.warning("DMCC cursor poll unavailable server_id=%s", server_id)
        except Exception:
            _LOGGER.exception("DMCC cursor poll failed server_id=%s", server_id)

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
        # A rotation or tail-window gap has no unambiguous resume position.
        # Establish the new baseline without replaying prior log content.
        return ""

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
