"""bot/mod/dmcc/services/v3_features.py

Modification():

- Provide one typed, bounded surface for DMCC v3 parsing, template and event options.
- Preserve legacy defaults; enabling the preview is explicit and reversible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
import re

PARSING_FLAGS: dict[str, tuple[str, ...]] = {
    "discord_to_minecraft": (
        "markdown", "attachments", "stickers", "unicode_emojis",
        "custom_emojis", "mentions", "hyperlinks", "embeds", "components",
        "timestamps", "ansi_code_blocks", "polls",
    ),
    "minecraft_to_discord": (
        "custom_emojis", "unicode_emojis", "mentions", "markdown",
        "hyperlinks", "timestamps",
    ),
    "minecraft_to_minecraft": (
        "markdown", "unicode_emojis", "custom_emojis",
        "mentions", "hyperlinks", "timestamps",
    ),
}
_ALIAS = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_SNOWFLAKE = re.compile(r"^[0-9]{15,20}$")
_EMOJI_TOKEN = re.compile(r"^<a?:[A-Za-z0-9_]{1,32}:[0-9]{15,20}>$")

SOURCE_EVENTS = frozenset(("broadcast", "say", "tell_raw", "me", "msg", "player_command"))
TEMPLATE_EVENTS = frozenset((
    "user_message", "system_message", "response", "command",
    "reaction", "edit", "edited_message", "delete",
))


def _flags(raw: object, names: tuple[str, ...], *, default: bool) -> Mapping[str, bool]:
    if not isinstance(raw, Mapping) or set(raw) - set(names):
        raise ValueError("unknown v3 parsing option")
    values: dict[str, bool] = {}
    for name in names:
        value = raw.get(name, default)
        if type(value) is not bool:
            raise ValueError(f"v3 feature {name} must be boolean")
        values[name] = value
    return MappingProxyType(values)


@dataclass(frozen=True, slots=True)
class V3FeatureConfig:
    enabled: bool = False
    parsing: Mapping[str, Mapping[str, bool]] = field(default_factory=lambda: MappingProxyType({
        name: MappingProxyType({flag: True for flag in flags})
        for name, flags in PARSING_FLAGS.items()
    }))
    source_events: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({
        name: name != "msg" for name in SOURCE_EVENTS
    }))
    minecraft_emoji_aliases: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    minecraft_glyph_aliases: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    minecraft_mention_ids: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    private_messages: bool = False
    templates: Mapping[str, tuple[Mapping[str, object], ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def from_mapping(cls, value: object) -> "V3FeatureConfig":
        if not isinstance(value, Mapping):
            raise ValueError("v3_features must be a mapping")
        if set(value) - {"enabled", "message_parsing", "source_events", "templates",
                          "minecraft_emoji_aliases", "minecraft_glyph_aliases",
                          "minecraft_mention_ids", "private_messages"}:
            raise ValueError("unknown v3_features options")
        enabled = value.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("v3_features.enabled must be boolean")
        parsing = value.get("message_parsing", {})
        if not isinstance(parsing, Mapping) or set(parsing) - set(PARSING_FLAGS):
            raise ValueError("invalid v3 message_parsing")
        parser = MappingProxyType({
            direction: _flags(parsing.get(direction, {}), names, default=True)
            for direction, names in PARSING_FLAGS.items()
        })
        private_messages = value.get("private_messages", False)
        if type(private_messages) is not bool:
            raise ValueError("private_messages must be a boolean")
        raw_sources = value.get("source_events", {})
        sources = _flags(raw_sources, tuple(sorted(SOURCE_EVENTS)), default=True)
        # "msg" source routing is only public when the Bridge explicitly marks
        # the exact @a recipient selector. Consent-scoped private events are a
        # separate packet and are never sent through MinecraftDiscordRelay.
        allowed_sources = dict(sources)
        raw_templates = value.get("templates", {})
        if not isinstance(raw_templates, Mapping) or set(raw_templates) - TEMPLATE_EVENTS:
            raise ValueError("invalid v3 templates")
        if len(raw_templates) > 16:
            raise ValueError("too many v3 templates")
        from .v3_templates import validate_segments
        templates = MappingProxyType({
            key: validate_segments(segment_list)
            for key, segment_list in raw_templates.items()
        })
        emoji = cls._mappings(value.get("minecraft_emoji_aliases", {}), emoji=True)
        mentions = cls._mappings(value.get("minecraft_mention_ids", {}), emoji=False)
        glyphs = cls._glyph_mappings(value.get("minecraft_glyph_aliases", {}))
        return cls(
            enabled=enabled,
            parsing=parser,
            source_events=MappingProxyType(allowed_sources),
            minecraft_emoji_aliases=emoji,
            minecraft_glyph_aliases=glyphs,
            minecraft_mention_ids=mentions,
            private_messages=private_messages,
            templates=templates,
        )

    @staticmethod
    def _mappings(raw: object, *, emoji: bool) -> Mapping[str, str]:
        if not isinstance(raw, Mapping) or len(raw) > 256:
            raise ValueError("invalid v3 alias mappings")
        mapped: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not _ALIAS.fullmatch(key):
                raise ValueError("invalid v3 alias name")
            if not isinstance(value, str) or not (
                _EMOJI_TOKEN.fullmatch(value) if emoji else _SNOWFLAKE.fullmatch(value)
            ):
                raise ValueError("invalid v3 alias target")
            mapped[key.casefold()] = value
        return MappingProxyType(mapped)

    @staticmethod
    def _glyph_mappings(raw: object) -> Mapping[str, str]:
        if not isinstance(raw, Mapping) or len(raw) > 256:
            raise ValueError("invalid Minecraft font glyph mappings")
        result: dict[str, str] = {}
        for key, glyph in raw.items():
            if not isinstance(key, str) or not _ALIAS.fullmatch(key):
                raise ValueError("invalid Minecraft font glyph name")
            if (not isinstance(glyph, str) or not 1 <= len(glyph) <= 8
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in glyph)
                    or "\\" in glyph or "@everyone" in glyph.casefold() or "@here" in glyph.casefold()):
                raise ValueError("invalid Minecraft font glyph value")
            result[key.casefold()] = glyph
        return MappingProxyType(result)

    def allows(self, direction: str, flag: str) -> bool:
        return self.enabled and bool(self.parsing.get(direction, {}).get(flag, False))

    def allows_source(self, name: str) -> bool:
        return self.enabled and bool(self.source_events.get(name, False))

    def template(self, name: str) -> tuple[Mapping[str, object], ...] | None:
        return self.templates.get(name) if self.enabled else None


DEFAULT_V3_FEATURES: dict[str, object] = {"enabled": False}
