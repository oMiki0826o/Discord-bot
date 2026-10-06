"""bot/mod/dmcc/services/discord_relay.py

bot/mod/dmcc/dmcc/services/discord_relay.py

Modification():

- 實作 Discord 訊息轉送到已映射 Minecraft Server 的獨立業務邏輯。

本檔不依賴 discord.py；Discord Cog 只負責提供 channel、author 與 content。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

from ..repositories.state import JsonStateRepository


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
    ) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._repository = repository
        self._gateway = gateway
        self._history_limit = history_limit
        self._messages: OrderedDict[str, _RelayedMessage] = OrderedDict()

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
    ) -> bool:
        """Forward a Discord create event and retain only transient edit/delete metadata."""

        if not isinstance(message_id, str) or not message_id.strip():
            return False
        if not isinstance(author_name, str) or not author_name.strip():
            return False
        normalized_content = content.strip() if isinstance(content, str) else ""
        attachments = tuple(url.strip() for url in attachment_urls if isinstance(url, str) and url.strip())
        if not normalized_content and not attachments:
            return False
        lines: list[str] = []
        if isinstance(reply_preview, str) and reply_preview.strip():
            lines.append("↪ " + reply_preview.strip()[:500])
        if normalized_content:
            lines.append(f"<{author_name.strip()}> {normalized_content}")
        lines.extend("Attachment: " + url for url in attachments[:5])
        delivered = await self._forward(channel_id, "\n".join(lines))
        if delivered:
            self._remember(message_id, _RelayedMessage(
                self._repository.server_for_channel(channel_id) or "",
                author_name.strip(),
                normalized_content,
            ))
        return delivered

    async def forward_edit(self, message_id: str, updated_content: str) -> bool:
        """Emit a bounded edit notice only to the server that received the original message."""

        previous = self._messages.get(message_id)
        normalized = updated_content.strip() if isinstance(updated_content, str) else ""
        if previous is None or not normalized or normalized == previous.content:
            return False
        delivered = await self._send_to_server(
            previous.server_id,
            f"* {previous.author_name} edited: {previous.content[:500]} → {normalized[:500]}",
        )
        if delivered:
            self._remember(message_id, _RelayedMessage(previous.server_id, previous.author_name, normalized))
        return delivered

    async def forward_delete(self, message_id: str) -> bool:
        """Emit a deletion notice only when the original relayed record still exists."""

        previous = self._messages.pop(message_id, None)
        if previous is None:
            return False
        return await self._send_to_server(previous.server_id, f"* {previous.author_name} deleted a Discord message")

    async def _forward(self, channel_id: str, message: str) -> bool:
        if not isinstance(message, str) or not message.strip():
            return False
        server_id = self._repository.server_for_channel(channel_id)
        if server_id is None:
            return False
        return await self._send_to_server(server_id, message)

    async def _send_to_server(self, server_id: str, message: str) -> bool:
        if not server_id:
            return False
        try:
            await self._gateway.send_minecraft_message(server_id, message)
        except LookupError:
            return False
        return True

    def _remember(self, message_id: str, record: _RelayedMessage) -> None:
        self._messages.pop(message_id, None)
        self._messages[message_id] = record
        while len(self._messages) > self._history_limit:
            self._messages.popitem(last=False)
