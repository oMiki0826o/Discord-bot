"""bot/mod/dmcc/services/v3_templates.py

Modification():

- Compile safe DMCC v3-style rich segment templates with inline message insertion.
- Reject arbitrary placeholders, colors, text-component actions and oversized output.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from string import Formatter
import re

_FIELDS = frozenset(("server", "server_color", "effective_name", "role_color", "message"))
_BOOL_STYLE = frozenset(("bold", "italic", "underlined", "strikethrough", "obfuscated"))
_COLORS = frozenset((
    "white", "gray", "dark_gray", "black", "dark_blue",
    "dark_green", "dark_aqua", "dark_red", "dark_purple",
    "gold", "blue", "green", "aqua", "red", "light_purple", "yellow",
))
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_SEGMENTS = 128
_MAX_UNITS = 1800


def _fields(value: str) -> None:
    for _, name, spec, conversion in Formatter().parse(value):
        if name is not None and (name not in _FIELDS or spec or conversion):
            raise ValueError("unsupported v3 template placeholder")


def validate_segments(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 32:
        raise ValueError("v3 segment template must contain 1..32 entries")
    compiled: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - ({"text", "color"} | _BOOL_STYLE):
            raise ValueError("unsafe v3 template segment")
        text = item.get("text")
        color = item.get("color", "white")
        if not isinstance(text, str) or len(text) > 800:
            raise ValueError("invalid v3 template text")
        if not isinstance(color, str) or (color not in _COLORS and not _HEX.fullmatch(color) and color not in ("{role_color}", "{server_color}")):
            raise ValueError("invalid v3 template color")
        _fields(text)
        for key in _BOOL_STYLE:
            if type(item.get(key, False)) is not bool:
                raise ValueError("invalid v3 style flag")
        compiled.append(dict(item))
    return tuple(compiled)


def _clip(text: str, remaining: int) -> str:
    out: list[str] = []
    for ch in text:
        units = 2 if ord(ch) > 0xFFFF else 1
        if units > remaining:
            break
        out.append(ch)
        remaining -= units
    return "".join(out)


def render_segments(
    spec: Sequence[Mapping[str, object]],
    values: Mapping[str, str],
    body: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return constrained Minecraft rich-text segments in the original template order."""
    safe_values = {key: str(values.get(key, ""))[:256] for key in _FIELDS}
    # The actual message is inserted as parsed segments, never formatted as a string.
    safe_values["message"] = ""
    output: list[dict[str, object]] = []
    remaining = _MAX_UNITS

    def emit(value: Mapping[str, object]) -> None:
        nonlocal remaining
        if remaining <= 0 or len(output) >= _MAX_SEGMENTS:
            return
        raw = value.get("text", "")
        if not isinstance(raw, str):
            return
        part = dict(value)
        part["text"] = _clip(raw, remaining)
        remaining -= len(str(part["text"]).encode("utf-16-le")) // 2
        if part["text"]:
            output.append(part)

    for template in validate_segments(spec):
        text = str(template.get("text", ""))
        color = str(template.get("color", "white"))
        if color in ("{role_color}", "{server_color}"):
            selected = safe_values[color[1:-1]]
            color = selected if selected in _COLORS or _HEX.fullmatch(selected) else "white"
        basis = {
            "color": color,
            **{key: bool(template.get(key, False)) for key in _BOOL_STYLE},
        }
        parts = text.split("{message}")
        for index, fragment in enumerate(parts):
            if fragment:
                emit({**basis, "text": fragment.format_map(safe_values)})
            if index + 1 < len(parts):
                for body_item in body:
                    emit(body_item)
    return output
