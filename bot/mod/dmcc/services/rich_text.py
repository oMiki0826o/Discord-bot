"""bot/mod/dmcc/services/rich_text.py

Modification():

- Pure-Python, bounded Discord Markdown to Minecraft style segment conversion. This intentionally supports only formatting, not untrusted Minecraft commands, click actions, arbitrary colors or JSON text-component fields.
"""
from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ANSI = re.compile(r"\x1b\[[0-9;]{0,30}[A-Za-z]")
_MARKS = (
    ("**", "bold"), ("__", "underlined"), ("~~", "strikethrough"),
    ("`", "code"), ("*", "italic"), ("_", "italic"),
)
_LIMIT = 1800
_MAX_SEGMENTS = 128


def _truncate_utf16(text: str, limit: int) -> str:
    """Minecraft Java text length counts UTF-16 code units, not code points."""
    length = 0
    result: list[str] = []
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if length + size > limit:
            break
        result.append(char)
        length += size
    return "".join(result)


def parse_discord_markdown(message: str) -> list[dict[str, object]]:
    """Decode a fixed safe subset of Markdown into validated Component style data."""
    if not isinstance(message, str) or not message:
        return []
    clean = _truncate_utf16(_CONTROL.sub("", _ANSI.sub("", message.replace("\r", " "))), _LIMIT)
    state = {"bold": False, "italic": False, "underlined": False, "strikethrough": False, "code": False}
    pieces: list[dict[str, object]] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        part = {
            "text": "".join(buf),
            "bold": state["bold"] and not state["code"],
            "italic": state["italic"] and not state["code"],
            "underlined": state["underlined"] and not state["code"],
            "strikethrough": state["strikethrough"] and not state["code"],
            "color": "gray" if state["code"] else "white",
        }
        buf.clear()
        if pieces and all(pieces[-1][key] == part[key] for key in part if key != "text"):
            pieces[-1]["text"] += part["text"]
        else:
            pieces.append(part)

    pos = 0
    while pos < len(clean):
        if clean[pos] == "\\" and pos + 1 < len(clean) and clean[pos + 1] in "*_~`\\":
            buf.append(clean[pos + 1])
            pos += 2
            continue
        if (
            clean.startswith("**", pos) and not state["bold"]
            and clean.find("**", pos + 2) < 0
        ):
            buf.append("**")
            pos += 2
            continue
        if (
            clean.startswith("__", pos) and not state["underlined"]
            and clean.find("__", pos + 2) < 0
        ):
            buf.append("__")
            pos += 2
            continue
        matched = False
        for symbol, property_name in _MARKS:
            if not clean.startswith(symbol, pos):
                continue
            if state["code"] and property_name != "code":
                continue
            # A lone unmatched opening delimiter remains readable text.
            if not state[property_name] and clean.find(symbol, pos + len(symbol)) < 0:
                continue
            flush()
            state[property_name] = not state[property_name]
            pos += len(symbol)
            matched = True
            break
        if not matched:
            buf.append(clean[pos])
            pos += 1
    flush()
    # Very fragmented content is kept bounded and avoids oversized Bedrock packets.
    if len(pieces) > _MAX_SEGMENTS:
        keep = pieces[:_MAX_SEGMENTS - 1]
        tail = "".join(str(item["text"]) for item in pieces[_MAX_SEGMENTS - 1:])
        keep.append({
            "text": tail,
            "bold": False,
            "italic": False,
            "underlined": False,
            "strikethrough": False,
            "color": "white",
        })
        return keep
    return pieces
