"""bot/mod/dmcc/services/monitoring.py

Modification():

- Maintain validated Minecraft telemetry snapshots and rate-limited Discord monitoring.
- Report sustained MSPT degradation and recovery without blocking the Bridge gateway.

"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import math
import time
from collections.abc import Callable, Mapping

from ..events import MinecraftEvent

LOGGER = logging.getLogger(__name__)


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label} out of bounds")
    return result


def _int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _channel(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or not 15 <= len(value) <= 20:
        raise ValueError("channel IDs must contain 15-20 ASCII digits")
    return value


@dataclass(frozen=True, slots=True)
class MonitorTarget:
    label: str
    alert_channel_id: str | None
    topic_channel_id: str | None
    status_voice_channel_id: str | None
    mspt_threshold: float = 45.0
    mspt_recovery: float = 40.0
    player_count_voice_channel_id: str | None = None


@dataclass(frozen=True, slots=True)
class MonitoringConfig:
    enabled: bool = False
    presence: bool = False
    interval_seconds: float = 60.0
    stale_seconds: float = 180.0
    alert_duration_seconds: float = 60.0
    alert_cooldown_seconds: float = 600.0
    channel_cooldown_seconds: float = 600.0
    servers: Mapping[str, MonitorTarget] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: object, server_ids: set[str]) -> "MonitoringConfig":
        if not isinstance(raw, Mapping):
            raise ValueError("monitoring must be an object")
        names = {"enabled", "presence", "interval_seconds", "stale_seconds",
                 "alert_duration_seconds", "alert_cooldown_seconds", "channel_cooldown_seconds", "servers"}
        if set(raw) - names:
            raise ValueError("unknown monitoring configuration keys")
        enabled, presence = raw.get("enabled", False), raw.get("presence", False)
        if type(enabled) is not bool or type(presence) is not bool:
            raise ValueError("monitoring enabled and presence must be booleans")
        interval = _number(raw.get("interval_seconds", 60), "interval_seconds", 30, 3600)
        stale = _number(raw.get("stale_seconds", 180), "stale_seconds", 60, 7200)
        duration = _number(raw.get("alert_duration_seconds", 60), "alert_duration_seconds", 0, 3600)
        alert_cooldown = _number(raw.get("alert_cooldown_seconds", 600), "alert_cooldown_seconds", 60, 86400)
        channel_cooldown = _number(raw.get("channel_cooldown_seconds", 600), "channel_cooldown_seconds", 600, 86400)
        servers = raw.get("servers", {})
        if not isinstance(servers, Mapping):
            raise ValueError("monitoring.servers must be an object")
        results: dict[str, MonitorTarget] = {}
        for name, options in servers.items():
            if name not in server_ids or not isinstance(options, Mapping):
                raise ValueError("unknown monitoring server_id or malformed server config")
            fields = {"label", "alert_channel_id", "topic_channel_id", "status_voice_channel_id",
                      "player_count_voice_channel_id", "mspt_threshold", "mspt_recovery"}
            if set(options) - fields:
                raise ValueError("unknown monitor target option")
            label = options.get("label", name)
            if not isinstance(label, str) or not label.strip() or len(label) > 60:
                raise ValueError("monitoring label must be nonempty and <=60 chars")
            threshold = _number(options.get("mspt_threshold", 45), "mspt_threshold", 1, 2000)
            recovery = _number(options.get("mspt_recovery", min(40, threshold - 0.1)), "mspt_recovery", 0, 1999)
            if recovery >= threshold:
                raise ValueError("mspt_recovery must be less than mspt_threshold")
            results[name] = MonitorTarget(
                label.strip(), _channel(options.get("alert_channel_id")),
                _channel(options.get("topic_channel_id")), _channel(options.get("status_voice_channel_id")),
                threshold, recovery, _channel(options.get("player_count_voice_channel_id")),
            )
        return cls(enabled, presence, interval, stale, duration, alert_cooldown, channel_cooldown, results)


@dataclass(frozen=True, slots=True)
class Metrics:
    mspt: float
    online_players: int
    max_players: int
    received: float


class MonitoringService:
    """Caches authenticated Bridge events and performs bounded Discord operations.

    Metrics expire to 'unknown' rather than being interpreted as zero or healthy.
    All Discord calls are best-effort; user-set Presence is untouched unless opted in.
    """

    def __init__(
        self, bot: object, manager: object, config: MonitoringConfig,
        *, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bot = bot
        self._manager = manager
        self.config = config
        self._clock = clock
        self._metrics: dict[str, Metrics] = {}
        self._high_since: dict[str, float] = {}
        self._alerting: set[str] = set()
        self._last_alert: dict[str, float] = {}
        self._last_edit: dict[str, tuple[str, float]] = {}
        self._last_presence: tuple[str, str] | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def latest(self, server_id: str) -> Metrics | None:
        if not self.config.enabled or self._manager.get(server_id) is None:
            return None
        metric = self._metrics.get(server_id)
        if metric is None or self._clock() - metric.received > self.config.stale_seconds:
            return None
        return metric

    async def on_event(self, event: MinecraftEvent) -> None:
        if not self.config.enabled or event.type != "server_metrics" or event.server_id not in self.config.servers:
            return
        data = event.data
        try:
            mspt = _number(data.get("mspt"), "mspt", 0, 2000)
            online = _int(data.get("online_players"), "online_players", 0, 100000)
            capacity = _int(data.get("max_players"), "max_players", 0, 100000)
            if online > capacity:
                return
            if "tps" in data:
                _number(data["tps"], "tps", 0, 20.1)
        except ValueError:
            return
        self._metrics[event.server_id] = Metrics(mspt, online, capacity, self._clock())

    def start(self) -> None:
        if not self.config.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="dmcc-monitoring")

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                LOGGER.exception("DMCC monitoring cycle failed")
            await asyncio.sleep(self.config.interval_seconds)

    async def run_once(self) -> None:
        if not self.config.enabled or self._closed:
            return
        active = False
        online_total = 0
        for server_id, target in self.config.servers.items():
            connected = self._manager.get(server_id) is not None
            metrics = self.latest(server_id)
            if connected:
                active = True
            if metrics is not None:
                online_total += metrics.online_players
            await self._check_alert(server_id, target, metrics)
            online_status = "Online" if connected else "Offline"
            suffix = (
                f"{metrics.online_players}/{metrics.max_players} | {metrics.mspt:.1f} MSPT"
                if metrics is not None else ("metrics unavailable" if connected else "")
            )
            topic = f"{target.label} | {online_status}" + (f" | {suffix}" if suffix else "")
            voice = f"{target.label} · {online_status}"
            await self._edit_channel(target.topic_channel_id, "topic", topic[:1024])
            await self._edit_channel(target.status_voice_channel_id, "name", voice[:100])
            count_text = (
                f"{metrics.online_players}/{metrics.max_players}"
                if metrics is not None else "—/—"
            )
            await self._edit_channel(
                target.player_count_voice_channel_id, "name",
                f"{target.label} · Players: {count_text}"[:100],
            )
        if self.config.presence and hasattr(self._bot, "set_presence_override"):
            activity = f"Minecraft | {online_total} 人在線"
            status = "online" if online_total > 0 else ("idle" if active else "dnd")
            if self._last_presence != (activity, status):
                if self._bot.set_presence_override("dmcc", activity, status):
                    self._last_presence = (activity, status)
                    refresh = getattr(self._bot, "refresh_presence", None)
                    if refresh is not None:
                        try:
                            await refresh()
                        except Exception:
                            LOGGER.exception("DMCC presence update failed")

    async def _check_alert(
        self, server_id: str, target: MonitorTarget, metrics: Metrics | None,
    ) -> None:
        now = self._clock()
        if metrics is None:
            self._high_since.pop(server_id, None)
            return
        if metrics.mspt >= target.mspt_threshold:
            start = self._high_since.setdefault(server_id, now)
            if (
                server_id not in self._alerting
                and now - start >= self.config.alert_duration_seconds
                and now - self._last_alert.get(server_id, -float("inf")) >= self.config.alert_cooldown_seconds
            ):
                sent = await self._send_alert(target, f"**{target.label} MSPT 警告：{metrics.mspt:.1f} ms（門檻 {target.mspt_threshold:.1f} ms）**")
                if sent:
                    self._alerting.add(server_id)
                    self._last_alert[server_id] = now
        elif metrics.mspt <= target.mspt_recovery:
            self._high_since.pop(server_id, None)
            if server_id in self._alerting:
                sent = await self._send_alert(target, f"**{target.label} MSPT 已恢復：{metrics.mspt:.1f} ms**")
                if sent:
                    self._alerting.discard(server_id)
                    self._last_alert[server_id] = now
        else:
            self._high_since.pop(server_id, None)

    async def _send_alert(self, target: MonitorTarget, content: str) -> bool:
        if not target.alert_channel_id:
            return False
        channel = self._channel(target.alert_channel_id)
        if channel is None or not hasattr(channel, "send"):
            return False
        try:
            import discord
            await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
            return True
        except Exception:
            LOGGER.exception("DMCC monitoring alert failed for %s", target.label)
            return False

    def _channel(self, channel_id: str | None) -> object | None:
        if channel_id is None:
            return None
        getter = getattr(self._bot, "get_channel", None)
        return getter(int(channel_id)) if getter else None

    async def _edit_channel(self, channel_id: str | None, field_name: str, value: str) -> None:
        if channel_id is None:
            return
        cache_key = f"{channel_id}:{field_name}"
        cached = self._last_edit.get(cache_key)
        if cached is not None:
            if cached[0] == value or self._clock() - cached[1] < self.config.channel_cooldown_seconds:
                return
        channel = self._channel(channel_id)
        if channel is None or not hasattr(channel, "edit"):
            return
        try:
            await channel.edit(**{field_name: value})
            self._last_edit[cache_key] = (value, self._clock())
        except Exception:
            LOGGER.exception("DMCC channel status update failed for %s", channel_id)

    async def close(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._last_presence is not None and hasattr(self._bot, "clear_presence_override"):
            await self._bot.clear_presence_override("dmcc")
