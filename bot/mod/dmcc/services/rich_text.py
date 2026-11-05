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
    ("||", "obfuscated"),
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


def _parse_plain_markdown(message: str) -> list[dict[str, object]]:
    """Decode a fixed safe subset of Markdown into validated Component style data."""
    if not isinstance(message, str) or not message:
        return []
    clean = _truncate_utf16(_CONTROL.sub("", _ANSI.sub("", message.replace("\r", " "))), _LIMIT)
    state = {"bold": False, "italic": False, "underlined": False, "strikethrough": False, "obfuscated": False, "code": False}
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
            "obfuscated": state["obfuscated"] and not state["code"],
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
            "obfuscated": False,
            "color": "white",
        })
        return keep
    return pieces



_ANSI_BLOCK = re.compile(r"\x60\x60\x60ansi[ \t]*\n([\s\S]*?)\x60\x60\x60", re.IGNORECASE)
_ANSI_SGR = re.compile(r"\x1b\[([0-9;]{1,30})m")
_ANSI_PALETTE = {
    30: "#555555", 31: "#AA0000", 32: "#00AA00",
    33: "#FFAA00", 34: "#5555FF", 35: "#AA00AA",
    36: "#00AAAA", 37: "#AAAAAA", 90: "#555555",
    91: "#FF5555", 92: "#55FF55", 93: "#FFFF55",
    94: "#5555FF", 95: "#FF55FF", 96: "#55FFFF",
    97: "#FFFFFF",
}


def _ansi_segments(source: str) -> list[dict[str, object]]:
    """Render Discord's ANSI code-fence subset without passing escape codes onward."""
    result: list[dict[str, object]] = []
    color = "gray"
    start = 0

    def emit(chunk: str) -> None:
        safe = _CONTROL.sub("", _ANSI.sub("", chunk.replace("\r", " ")))
        if not safe:
            return
        segment: dict[str, object] = {
            "text": safe,
            "bold": False, "italic": False, "underlined": False,
            "strikethrough": False, "obfuscated": False, "color": color,
        }
        if result and all(result[-1].get(key) == val for key, val in segment.items() if key != "text"):
            result[-1]["text"] = str(result[-1]["text"]) + safe
        else:
            result.append(segment)

    for match in _ANSI_SGR.finditer(source):
        emit(source[start:match.start()])
        for raw in match.group(1).split(";"):
            code = int(raw) if raw else 0
            if code == 0 or code == 39:
                color = "gray"
            elif code in _ANSI_PALETTE:
                color = _ANSI_PALETTE[code]
        start = match.end()
    emit(source[start:])
    return result


def parse_discord_markdown(message: str) -> list[dict[str, object]]:
    """Bounded inline Markdown plus safe fenced ANSI colors, preserving text order."""
    if not isinstance(message, str) or not message:
        return []
    if not _ANSI_BLOCK.search(message):
        return _parse_plain_markdown(message)

    # Restrict the work before regular expression parsing, even for huge inputs.
    source = message[:12000]
    parts: list[dict[str, object]] = []
    start = 0
    for match in _ANSI_BLOCK.finditer(source):
        parts.extend(_parse_plain_markdown(source[start:match.start()]))
        parts.extend(_ansi_segments(match.group(1)))
        start = match.end()
    parts.extend(_parse_plain_markdown(source[start:]))

    output: list[dict[str, object]] = []
    remaining = _LIMIT
    for part in parts:
        text = _truncate_utf16(str(part["text"]), remaining)
        if not text:
            break
        clean = {**part, "text": text}
        if output and all(output[-1].get(key) == val for key, val in clean.items() if key != "text"):
            output[-1]["text"] = str(output[-1]["text"]) + text
        else:
            output.append(clean)
        remaining -= len(text.encode("utf-16-le")) // 2
        if remaining == 0:
            break

    if len(output) > _MAX_SEGMENTS:
        tail = "".join(str(item["text"]) for item in output[_MAX_SEGMENTS - 1:])
        output = output[:_MAX_SEGMENTS - 1] + [{
            "text": tail, "bold": False, "italic": False, "underlined": False,
            "strikethrough": False, "obfuscated": False, "color": "white",
        }]
    return output


# Discord's guild color is untrusted presentation metadata, never an authorization grant.
_AUTHOR_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def colorize_author_prefix(
    segments: list[dict[str, object]], prefix: str, color: str | None,
) -> list[dict[str, object]]:
    """Color only the exact sender prefix, never message text or Markdown styles."""
    if not isinstance(color, str) or not _AUTHOR_COLOR.fullmatch(color):
        return segments
    if not segments or not isinstance(prefix, str) or not prefix:
        return segments
    first = segments[0]
    raw = first.get("text")
    if not isinstance(raw, str) or not raw.startswith(prefix):
        return segments
    copied = {**first, "text": prefix, "color": color.upper()}
    suffix = raw[len(prefix):]
    result = [copied]
    if suffix:
        if len(segments) >= _MAX_SEGMENTS:
            return segments
        result.append({**first, "text": suffix})
    result.extend(segments[1:])
    return result
