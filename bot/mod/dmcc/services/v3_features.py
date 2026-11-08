"""bot/mod/dmcc/services/v3_features.py

Modification():

- Provide one typed, bounded surface for DMCC v3 parsing, template and event options.
- Preserve legacy defaults; enabling the preview is explicit and reversible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType

PARSING_FLAGS: dict[str, tuple[str, ...]] = {
    "discord_to_minecraft": (
        "markdown", "attachments", "stickers", "unicode_emojis",
        "custom_emojis", "mentions", "hyperlinks", "embeds", "components",
        "timestamps", "ansi_code_blocks", "polls",
    ),
    "minecraft_to_discord": ("custom_emojis", "mentions"),
    "minecraft_to_minecraft": (
        "markdown", "unicode_emojis", "custom_emojis",
        "mentions", "hyperlinks", "timestamps",
    ),
}
SOURCE_EVENTS = frozenset(("say", "tell_raw", "me", "msg", "player_command"))
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
    templates: Mapping[str, tuple[Mapping[str, object], ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def from_mapping(cls, value: object) -> "V3FeatureConfig":
        if not isinstance(value, Mapping):
            raise ValueError("v3_features must be a mapping")
        if set(value) - {"enabled", "message_parsing", "source_events", "templates"}:
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
        raw_sources = value.get("source_events", {})
        sources = _flags(raw_sources, tuple(sorted(SOURCE_EVENTS)), default=False)
        # "msg" is never broadcast to Discord by the public-message pipeline:
        # it is kept as a schema option for a future private, consent-based route.
        allowed_sources = dict(sources)
        allowed_sources["msg"] = False
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
        return cls(enabled, parser, MappingProxyType(allowed_sources), templates)

    def allows(self, direction: str, flag: str) -> bool:
        return self.enabled and bool(self.parsing.get(direction, {}).get(flag, False))

    def allows_source(self, name: str) -> bool:
        return self.enabled and bool(self.source_events.get(name, False))

    def template(self, name: str) -> tuple[Mapping[str, object], ...] | None:
        return self.templates.get(name) if self.enabled else None


DEFAULT_V3_FEATURES: dict[str, object] = {"enabled": False}
