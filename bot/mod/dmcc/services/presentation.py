"""bot/mod/dmcc/services/presentation.py

Modification():

- Implement and verify Minecraft Bridge presentation and safe Discord routing.

Validated Discord presentation rules for Minecraft Bridge events.

This module has no discord.py dependency and never persists Webhook secrets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from string import Formatter
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from ..events import MinecraftEvent
from .public_commands import sanitize_public_player_command

EVENT_TYPES = frozenset({
    "player_chat", "player_join", "player_quit", "player_death",
    "player_advancement", "player_gamemode", "server_started", "server_stopping",
    "server_broadcast", "player_command",
})
_FIELDS = frozenset({
    "player", "server", "message", "death_message", "game_mode", "title", "label",
    "description", "advancement_type", "minecraft_uuid", "minecraft_version",
    "motd", "online_players", "max_players",
})
_EVENT_TEMPLATES = {
    "player_join": "**{player} 加入了 {server}**",
    "player_quit": "**{player} 離開了 {server}**",
    "player_death": "**{death_message}**",
    "player_advancement": "**{player} 完成了進度 [{title}]**",
    "player_gamemode": "**{player} 切換遊戲模式為 {game_mode}**",
    "server_started": "**{server} 已啟動**",
    "server_stopping": "**{server} 即將關閉**",
    "server_broadcast": "**[{server}] {player}: {message}**",
    "player_command": "**[{server}] {player}：{message}**",
}
_ENGLISH_EVENT_TEMPLATES = {
    "player_join": "**{player} joined {server}**",
    "player_quit": "**{player} left {server}**",
    "player_death": "**{death_message}**",
    "player_advancement": "**{player} made the advancement [{title}]**",
    "player_gamemode": "**{player} changed game mode to {game_mode}**",
    "server_started": "**{server} started**",
    "server_stopping": "**{server} is stopping**",
    "server_broadcast": "**[{server}] {player}: {message}**",
    "player_command": "**[{server}] {player} executed {message}**",
}
_LOCALES = frozenset({"zh_TW", "en_US"})
_DISCORD_WEBHOOK_PATH = re.compile(r"^/api/webhooks/[0-9]{15,20}/[^/\s]+$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_PLAYER_NAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")
_AVATAR_HOSTS = frozenset({"mc-heads.net", "crafatar.com", "cdn.discordapp.com", "media.discordapp.net"})


class PresentationError(ValueError):
    """Malformed presentation setting or unsupported template."""


@dataclass(frozen=True, slots=True)
class RouteConfig:
    mode: str = "bot"
    channel_id: str | None = None
    webhook_url: str | None = field(default=None, repr=False, compare=False)
    username: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class ServerPresentation:
    label: str
    chat: RouteConfig
    events: RouteConfig
    event_routes: Mapping[str, RouteConfig]
    event_channels: Mapping[str, str]
    templates: Mapping[str, str]
    disabled_events: frozenset[str]
    locale: str = "zh_TW"


@dataclass(frozen=True, slots=True)
class PresentationSettings:
    servers: Mapping[str, ServerPresentation]

    @classmethod
    def empty(cls) -> "PresentationSettings":
        return cls(MappingProxyType({}))

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        environ: Mapping[str, str] | None = None,
    ) -> "PresentationSettings":
        env = os.environ if environ is None else environ
        if not isinstance(raw, Mapping):
            raise PresentationError("presentation must be an object")
        if set(raw) - {"servers"}:
            raise PresentationError("unknown presentation configuration keys")
        servers = raw.get("servers", {})
        if not isinstance(servers, Mapping):
            raise PresentationError("presentation.servers must be an object")
        result: dict[str, ServerPresentation] = {}
        for server_id, item in servers.items():
            if not isinstance(server_id, str) or not server_id.strip():
                raise PresentationError("presentation server_id must be text")
            if not isinstance(item, Mapping):
                raise PresentationError("presentation server entry must be an object")
            if set(item) - {"label", "chat", "events", "event_routes", "event_channels", "templates", "disabled_events", "locale"}:
                raise PresentationError("unknown presentation server option")
            locale = item.get("locale", "zh_TW")
            if not isinstance(locale, str) or locale not in _LOCALES:
                raise PresentationError("presentation.locale must be zh_TW or en_US")
            label = item.get("label", server_id)
            if not isinstance(label, str) or not label.strip() or len(label) > 80:
                raise PresentationError("presentation.label must be non-empty and at most 80 characters")
            chat = _route(item.get("chat", {}), env, f"{server_id}.chat")
            events = _route(item.get("events", {}), env, f"{server_id}.events")
            raw_routes = item.get("event_routes", {})
            raw_channels = item.get("event_channels", {})
            raw_templates = item.get("templates", {})
            raw_disabled = item.get("disabled_events", [])
            if not isinstance(raw_routes, Mapping):
                raise PresentationError("event_routes must be an object")
            if not isinstance(raw_channels, Mapping):
                raise PresentationError("event_channels must be an object")
            if not isinstance(raw_templates, Mapping):
                raise PresentationError("templates must be an object")
            if not isinstance(raw_disabled, list):
                raise PresentationError("disabled_events must be a list")
            routes: dict[str, RouteConfig] = {}
            for kind, value in raw_routes.items():
                _event_name(kind)
                if kind == "player_chat":
                    raise PresentationError("player_chat must use the chat route")
                routes[kind] = _route(value, env, f"{server_id}.event_routes.{kind}")
            channels: dict[str, str] = {}
            templates: dict[str, str] = {}
            for kind, value in raw_channels.items():
                _event_name(kind)
                if kind == "player_chat":
                    raise PresentationError("player_chat must use chat.channel_id")
                selected = routes.get(kind, events)
                if selected.mode == "webhook":
                    raise PresentationError("event_channels cannot redirect Webhook routes; configure event_routes with its own webhook")
                channels[kind] = _channel(value)
            for kind, value in raw_templates.items():
                _event_name(kind)
                templates[kind] = _template(value, f"templates.{kind}")
            for kind in raw_disabled:
                _event_name(kind)
            result[server_id] = ServerPresentation(
                label.strip(), chat, events,
                MappingProxyType(routes), MappingProxyType(channels), MappingProxyType(templates),
                frozenset(raw_disabled), locale,
            )
        return cls(MappingProxyType(result))


@dataclass(frozen=True, slots=True)
class OutboundDiscordMessage:
    channel_id: str
    content: str
    mode: str
    username: str | None = None
    avatar_url: str | None = None
    webhook_url: str | None = field(default=None, repr=False, compare=False)
    fallback_content: str | None = None


def _event_name(value: object) -> None:
    if not isinstance(value, str) or value not in EVENT_TYPES:
        raise PresentationError("unsupported presentation event type")


def _channel(value: object) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or not 1 <= len(value) <= 20:
        raise PresentationError("channel_id must be a decimal Discord ID string")
    return value


def _template(raw: object, name: str) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
        raise PresentationError(f"{name} must be non-empty text of at most 2000 characters")
    try:
        fields = []
        for _, name, format_spec, conversion in Formatter().parse(raw):
            if name is not None:
                if format_spec or conversion:
                    raise PresentationError(f"{name} does not permit format modifiers")
                fields.append(name)
    except ValueError as exc:
        raise PresentationError(f"{name} has malformed braces") from exc
    if any(field not in _FIELDS for field in fields):
        raise PresentationError(f"{name} contains an unsupported placeholder")
    return raw


def _validate_webhook_url(url: str) -> None:
    # A Webhook URL is a credential. Never include the URL in exceptions or logs.
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
            and parsed.port is None
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and bool(_DISCORD_WEBHOOK_PATH.fullmatch(parsed.path))
        )
    except ValueError:
        valid = False
    if not valid:
        raise PresentationError("webhook_url_env must resolve to a Discord HTTPS webhook URL")


def _avatar_template(raw: object) -> str:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 400:
        raise PresentationError("avatar_url must be a short HTTPS URL")
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _AVATAR_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or parsed.query or parsed.fragment
            or not parsed.path.startswith("/")
        ):
            raise PresentationError("avatar_url must point to an approved HTTPS avatar host")
        for _, field, spec, conversion in Formatter().parse(parsed.path):
            if field is not None and (field not in {"player", "minecraft_uuid"} or spec or conversion):
                raise PresentationError("avatar_url contains an unsupported placeholder")
    except ValueError as exc:
        raise PresentationError("invalid avatar_url format") from exc
    return raw


def _route(raw: object, environ: Mapping[str, str], label: str) -> RouteConfig:
    if not isinstance(raw, Mapping):
        raise PresentationError(f"{label} must be an object")
    if set(raw) - {"mode", "channel_id", "webhook_url_env", "username", "avatar_url"}:
        raise PresentationError(f"{label} has unknown options")
    mode = raw.get("mode", "bot")
    if mode not in {"bot", "webhook"}:
        raise PresentationError(f"{label}.mode must be bot or webhook")
    channel_id = raw.get("channel_id")
    if channel_id is not None:
        channel_id = _channel(channel_id)
    username = raw.get("username")
    if username is not None:
        username = _template(username, f"{label}.username")
        if len(username) > 80:
            raise PresentationError(f"{label}.username must be at most 80 characters")
    secret_env = raw.get("webhook_url_env")
    url = None
    if mode == "webhook":
        if not isinstance(secret_env, str) or not secret_env.strip():
            raise PresentationError(f"{label}.webhook_url_env is required in webhook mode")
        url = environ.get(secret_env)
        if not url:
            raise PresentationError(f"{label}.webhook_url_env environment variable is missing")
        _validate_webhook_url(url)
    elif secret_env is not None:
        raise PresentationError(f"{label}.webhook_url_env requires webhook mode")
    avatar_url = raw.get("avatar_url")
    if avatar_url is not None:
        if mode != "webhook":
            raise PresentationError(f"{label}.avatar_url requires Webhook mode")
        avatar_url = _avatar_template(avatar_url)
    return RouteConfig(mode, channel_id, url, username, avatar_url)


def render_message(
    event: MinecraftEvent,
    profile: ServerPresentation,
    default_channel: str | None,
) -> OutboundDiscordMessage | None:
    """Build one safe, bounded message without contacting Discord or Minecraft."""
    if event.type not in EVENT_TYPES or event.type in profile.disabled_events:
        return None
    route = profile.chat if event.type == "player_chat" else profile.event_routes.get(event.type, profile.events)
    channel_id = profile.event_channels.get(event.type) or route.channel_id or default_channel
    if channel_id is None:
        return None
    data = event.data
    player = data.get("player_name")
    needs_player = event.type in {
        "player_chat", "player_join", "player_quit", "player_gamemode", "player_advancement",
        "player_command",
    }
    if needs_player and (not isinstance(player, str) or not player.strip()):
        return None
    if event.type in {"player_chat", "server_broadcast", "player_command"}:
        message = data.get("message")
        if not isinstance(message, str) or not message.strip():
            return None
    elif event.type == "player_death":
        death_message = data.get("death_message")
        if not isinstance(death_message, str) or not death_message.strip():
            return None
    elif event.type == "player_advancement":
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
    elif event.type == "player_gamemode":
        game_mode = data.get("game_mode")
        if not isinstance(game_mode, str) or not game_mode.strip():
            return None

    sanitized_command = None
    if event.type == "player_command":
        sanitized_command = sanitize_public_player_command(data.get("message"))
        if sanitized_command is None:
            return None

    values = {
        "server": profile.label, "player": player.strip() if isinstance(player, str) else "Server",
        "message": sanitized_command if sanitized_command is not None else str(data.get("message", "")).strip(),
        "death_message": str(data.get("death_message", "")).strip(),
        "title": str(data.get("title", "")).strip(),
        "game_mode": str(data.get("game_mode", "")).strip(),
        "label": str(data.get("advancement_type", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "advancement_type": str(data.get("advancement_type", "")).strip(),
        "minecraft_uuid": str(data.get("minecraft_uuid", "")).strip(),
        "minecraft_version": str(data.get("minecraft_version", "")).strip(),
        "motd": str(data.get("motd", "")).strip(),
        "online_players": str(data.get("online_players", "")).strip(),
        "max_players": str(data.get("max_players", "")).strip(),
    }
    if event.type == "player_chat":
        template = profile.templates.get(
            "player_chat",
            "{message}" if route.mode == "webhook" else "[{server}] <{player}> {message}",
        )
        content = template.format_map(values)
    else:
        defaults = _ENGLISH_EVENT_TEMPLATES if profile.locale == "en_US" else _EVENT_TEMPLATES
        content = profile.templates.get(event.type, defaults[event.type]).format_map(values)
    content = content.strip()[:1950]
    if not content:
        return None
    username = None
    avatar_url = None
    if route.mode == "webhook":
        name_pattern = route.username or (
            "[{server}] {player}" if event.type == "player_chat" else "{server}"
        )
        username = name_pattern.format_map(values)[:80]
        uuid = data.get("minecraft_uuid")
        valid_uuid = uuid if isinstance(uuid, str) and _UUID.fullmatch(uuid) else None
        valid_player = values["player"] if _PLAYER_NAME.fullmatch(values["player"]) else None
        if route.avatar_url is not None:
            if "{minecraft_uuid}" not in route.avatar_url or valid_uuid is not None:
                if "{player}" not in route.avatar_url or valid_player is not None:
                    avatar_url = route.avatar_url.format_map({
                        "minecraft_uuid": valid_uuid or "",
                        "player": valid_player or "",
                    })
        elif event.type == "player_chat":
            if valid_uuid is not None:
                avatar_url = f"https://mc-heads.net/avatar/{valid_uuid}/64"
            elif valid_player is not None:
                avatar_url = f"https://mc-heads.net/avatar/{valid_player}/64"
    return OutboundDiscordMessage(
        channel_id=channel_id,
        content=content,
        mode=route.mode,
        username=username,
        avatar_url=avatar_url,
        webhook_url=route.webhook_url,
        fallback_content=(
            f"[{profile.label}] <{values['player']}> {values['message']}"[:1950]
            if event.type == "player_chat" else content
        ),
    )
