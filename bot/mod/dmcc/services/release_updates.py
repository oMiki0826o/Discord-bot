"""Optional bounded update notifications for this Bot's official GitHub releases.

This service never installs, executes or downloads binaries. The release link is
validated against this repository's fixed GitHub Releases URL.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable, Mapping
from dataclasses import dataclass
import json
import logging
import re
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)
_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_REPO = "oMiki0826o/Discord-bot"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_URL_PREFIX = f"https://github.com/{_REPO}/releases/tag/"


@dataclass(frozen=True, slots=True)
class ReleaseCheckConfig:
    enabled: bool = False
    channel_id: str | None = None
    interval_seconds: int = 21600

    @classmethod
    def from_mapping(cls, raw: object) -> "ReleaseCheckConfig":
        if not isinstance(raw, Mapping) or set(raw) - {
            "enabled", "channel_id", "interval_seconds"
        }:
            raise ValueError("release_check must contain only enabled, channel_id and interval_seconds")
        enabled = raw.get("enabled", False)
        channel = raw.get("channel_id")
        interval = raw.get("interval_seconds", 21600)
        if type(enabled) is not bool or type(interval) is not int or not 3600 <= interval <= 86400:
            raise ValueError("invalid release_check flags or interval")
        if channel is not None and (
            not isinstance(channel, str) or not channel.isascii()
            or not channel.isdecimal() or not 15 <= len(channel) <= 20
        ):
            raise ValueError("invalid release_check channel_id")
        if enabled and channel is None:
            raise ValueError("enabled release_check requires a Discord channel_id")
        return cls(enabled, channel, interval)


def _version(raw: object) -> tuple[int, int, int] | None:
    if not isinstance(raw, str):
        return None
    match = _VERSION.fullmatch(raw)
    return tuple(map(int, match.groups())) if match else None


class ReleaseUpdateService:
    def __init__(
        self,
        config: ReleaseCheckConfig,
        sender: object,
        current_version: str,
        *,
        fetch_latest: Callable[[], Awaitable[Mapping[str, object]]] | None = None,
    ) -> None:
        if _version(current_version) is None:
            raise ValueError("current_version must be a stable triple")
        self.config = config
        self._sender = sender
        self._current = _version(current_version)
        self._fetch_latest = fetch_latest or _github_release
        self._announced: set[str] = set()
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> bool:
        if not self.config.enabled or self.config.channel_id is None:
            return False
        try:
            record = await self._fetch_latest()
            if not isinstance(record, Mapping) or record.get("draft") or record.get("prerelease"):
                return False
            tag = record.get("tag_name")
            newest = _version(tag)
            url = record.get("html_url")
            if newest is None or self._current is None or newest <= self._current:
                return False
            if not isinstance(tag, str) or not isinstance(url, str) or tag in self._announced:
                return False
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https" or parsed.netloc != "github.com"
                or parsed.query or parsed.fragment or parsed.username or parsed.password
                or not parsed.path.startswith("/" + _REPO + "/releases/tag/")
                or url != _URL_PREFIX + tag
            ):
                return False
            await self._sender.send_discord_message(
                self.config.channel_id,
                f"DMCC 模組有新版發布：{tag}（目前 {'.'.join(map(str, self._current))}）\n{url}\n請先確認 Minecraft 版本相容，再手動更新。",
            )
            self._announced.add(tag)
            return True
        except Exception:
            LOGGER.warning("DMCC release metadata unavailable; skipping this cycle")
            return False

    def start(self) -> None:
        if self.config.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="dmcc-self-release-check")

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.config.interval_seconds)

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def _github_release() -> Mapping[str, object]:
    import aiohttp
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout, headers={
        "User-Agent": "DMCC-Bridge-Release-Check",
        "Accept": "application/vnd.github+json",
    }) as session:
        async with session.get(_API_URL, allow_redirects=False) as response:
            if response.status != 200:
                raise RuntimeError("GitHub releases unavailable")
            payload = await response.content.read(131073)
            if len(payload) > 131072:
                raise ValueError("GitHub releases response exceeded limit")
            parsed = json.loads(payload)
            if not isinstance(parsed, dict):
                raise ValueError("unexpected GitHub release response")
            return parsed
