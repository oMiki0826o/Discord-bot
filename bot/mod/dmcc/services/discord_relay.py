"""bot/mod/dmcc/services/discord_relay.py

bot/mod/dmcc/dmcc/services/discord_relay.py

Modification():

- 實作 Discord 訊息轉送到已映射 Minecraft Server 的獨立業務邏輯。

本檔不依賴 discord.py；Discord Cog 只負責提供 channel、author 與 content。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol, Mapping, Sequence

from ..repositories.state import JsonStateRepository
from .message_format import format_discord_content, render_extras
from .rich_text import parse_discord_markdown, colorize_author_prefix
from .v3_features import V3FeatureConfig
from .v3_templates import render_segments


# ── Gateway Contract ──────────────────────


class MinecraftMessageSender(Protocol):
    """Relay Service 所需的最小 Gateway 傳送介面。"""

    async def send_minecraft_message(self, server_id: str, message: str) -> None:
        """向一台已認證 Minecraft Bridge 傳送純文字訊息。"""


@dataclass(frozen=True, slots=True)
class _RelayedMessage:
    """Minimal transient state needed to make edit/delete retain original routing."""

    server_id: str
    author_name: str
    content: str


# ── Relay Service ──────────────────────


class DiscordRelayService:
    """將 Discord 訊息安全地路由到唯一映射的 Minecraft Server。"""

    def __init__(
        self,
        repository: JsonStateRepository,
        gateway: MinecraftMessageSender,
        *,
        history_limit: int = 1_000,
        rich_chat: bool = False,
        features: V3FeatureConfig | None = None,
    ) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._repository = repository
        self._gateway = gateway
        self._history_limit = history_limit
        self._features = features or V3FeatureConfig()
        self._base_rich_chat = rich_chat
        self._rich_chat = rich_chat or self._features.enabled
        self._messages: OrderedDict[str, _RelayedMessage] = OrderedDict()

    def apply_preview_features(self, features: V3FeatureConfig) -> None:
        """Atomically replace only the optional display/parser feature snapshot."""
        self._features = features
        self._rich_chat = self._base_rich_chat or features.enabled

    async def forward_discord_message(
        self,
        channel_id: str,
        author_name: str,
        content: str,
    ) -> bool:
        """轉送一則映射頻道文字；未映射或離線時安全地略過。"""

        return await self._forward(channel_id, f"<{author_name.strip()}> {content.strip()}")

    async def forward_message(
        self,
        message_id: str,
        channel_id: str,
        author_name: str,
        content: str,
        *,
        reply_preview: str | None = None,
        attachment_urls: tuple[str, ...] = (),
        sticker_names: tuple[str, ...] = (),
        embed_summaries: tuple[tuple[str, str], ...] = (),
        poll_summary: tuple[str, Sequence[str]] | None = None,
        mention_names: Mapping[str, str] | None = None,
        author_color: str | None = None,
    ) -> bool:
        """Forward a Discord create event and retain only transient edit/delete metadata."""

        if not isinstance(message_id, str) or not message_id.strip():
            return False
        if not isinstance(author_name, str) or not author_name.strip():
            return False
        normalized_content = content.strip() if isinstance(content, str) else ""
        attachments = tuple((url.rsplit("/", 1)[-1][:80], url) for url in attachment_urls if isinstance(url, str))
        flags = self._features.parsing["discord_to_minecraft"]
        rendered = format_discord_content(
            normalized_content,
            mentions=mention_names if not self._features.enabled or flags["mentions"] else {},
            custom_emojis=not self._features.enabled or flags["custom_emojis"],
            timestamps=not self._features.enabled or flags["timestamps"],
        )
        extras = render_extras(
            attachments=attachments if not self._features.enabled or flags["attachments"] else (),
            stickers=sticker_names if not self._features.enabled or flags["stickers"] else (),
            embeds=embed_summaries if not self._features.enabled or flags["embeds"] else (),
            poll=poll_summary if not self._features.enabled or flags["polls"] else None,
        )
        if not rendered and not extras:
            return False
        lines: list[str] = []
        if isinstance(reply_preview, str) and reply_preview.strip():
            lines.append("↪ " + format_discord_content(reply_preview, mentions=mention_names, limit=300))
        if rendered:
            lines.append(f"<{author_name.strip()[:64]}> {rendered}")
        if extras:
            lines.append(extras)
        delivered = await self._forward(
            channel_id, "\n".join(lines),
            author_prefix=f"<{author_name.strip()[:64]}> " if rendered else None,
            author_color=author_color,
            template_kind="user_message", template_body=rendered,
            template_values={"effective_name": author_name.strip()[:64], "role_color": author_color or "white"},
        )
        if delivered:
            self._remember(message_id, _RelayedMessage(
                self._repository.server_for_channel(channel_id) or "",
                author_name.strip(),
                normalized_content,
            ))
        return delivered

    async def forward_reaction(
        self, message_id: str, reactor_name: str, emoji: str,
    ) -> bool:
        """Relay only reactions for messages originally forwarded by this bridge."""
        previous = self._messages.get(message_id)
        if previous is None or not reactor_name or not emoji:
            return False
        rendered = format_discord_content(emoji, limit=60)
        if not rendered:
            return False
        return await self._send_to_server(
            previous.server_id,
            f"* {reactor_name.strip()[:64]} reacted {rendered} to {previous.author_name[:64]}'s message",
            template_kind="reaction", template_body=rendered,
            template_values={"effective_name": reactor_name.strip()[:64]},
        )

    async def forward_edit(self, message_id: str, updated_content: str) -> bool:
        """Emit a bounded edit notice only to the server that received the original message."""

        previous = self._messages.get(message_id)
        normalized = updated_content.strip() if isinstance(updated_content, str) else ""
        if previous is None or not normalized or normalized == previous.content:
            return False
        delivered = await self._send_to_server(
            previous.server_id,
            f"* {previous.author_name} edited: {previous.content[:500]} → {normalized[:500]}",
            template_kind="edit", template_body=normalized,
            template_values={"effective_name": previous.author_name[:64]},
        )
        if delivered:
            self._remember(message_id, _RelayedMessage(previous.server_id, previous.author_name, normalized))
        return delivered

    async def forward_delete(self, message_id: str) -> bool:
        """Emit a deletion notice only when the original relayed record still exists."""

        previous = self._messages.pop(message_id, None)
        if previous is None:
            return False
        return await self._send_to_server(
            previous.server_id, f"* {previous.author_name} deleted a Discord message",
            template_kind="delete", template_body="",
            template_values={"effective_name": previous.author_name[:64]},
        )

    async def _forward(
        self, channel_id: str, message: str, *,
        author_prefix: str | None = None, author_color: str | None = None,
        template_kind: str | None = None, template_body: str | None = None,
        template_values: Mapping[str, str] | None = None,
    ) -> bool:
        if not isinstance(message, str) or not message.strip():
            return False
        server_id = self._repository.server_for_channel(channel_id)
        if server_id is None:
            return False
        return await self._send_to_server(
            server_id, message, author_prefix=author_prefix, author_color=author_color,
            template_kind=template_kind, template_body=template_body,
            template_values=template_values,
        )

    async def _send_to_server(
        self, server_id: str, message: str, *,
        author_prefix: str | None = None, author_color: str | None = None,
        template_kind: str | None = None, template_body: str | None = None,
        template_values: Mapping[str, str] | None = None,
    ) -> bool:
        if not server_id:
            return False
        try:
            if self._rich_chat and hasattr(self._gateway, "send_minecraft_segments"):
                flags = self._features.parsing["discord_to_minecraft"]
                def parse(text: str) -> list[dict[str, object]]:
                    if self._features.enabled and not flags["markdown"]:
                        return [{"text": text[:1800], "color": "white"}]
                    return parse_discord_markdown(text)
                segments = parse(message)
                if self._features.enabled and not flags["hyperlinks"]:
                    segments = [
                        {key: val for key, val in item.items()
                         if key not in {"click_url", "hover_text"}}
                        for item in segments
                    ]
                if self._features.enabled and template_kind:
                    template = self._features.template(template_kind)
                    if template:
                        values = {
                            "server": server_id, "server_color": "white",
                            **(template_values or {}),
                        }
                        segments = render_segments(template, values, parse(template_body or ""))
                if author_prefix and author_color and not (template_kind and self._features.template(template_kind)):
                    segments = colorize_author_prefix(segments, author_prefix, author_color)
                await self._gateway.send_minecraft_segments(server_id, segments)
            else:
                await self._gateway.send_minecraft_message(server_id, message)
        except LookupError:
            return False
        return True

    def _remember(self, message_id: str, record: _RelayedMessage) -> None:
        self._messages.pop(message_id, None)
        self._messages[message_id] = record
        while len(self._messages) > self._history_limit:
            self._messages.popitem(last=False)
