"""bot/mod/dmcc/application/channel_mappings.py
Use cases for the one-to-one Discord channel mapping.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Protocol


class ChannelMappingPort(Protocol):
    def set_channel_mapping(self, server_id: str, channel_id: str) -> None: ...

    def remove_channel_mapping(self, server_id: str) -> bool: ...

    def set_channel_group(self, channel_id: str, server_ids: tuple[str, ...], **options: bool) -> None: ...

    def remove_channel_group(self, channel_id: str) -> bool: ...


class ChannelMappingService:
    def __init__(self, repository: ChannelMappingPort) -> None:
        self._repository = repository

    def map(self, server_id: str, channel_id: str) -> None:
        self._repository.set_channel_mapping(server_id, channel_id)

    def unmap(self, server_id: str) -> bool:
        return self._repository.remove_channel_mapping(server_id)

    def map_group(self, channel_id: str, server_ids: tuple[str, ...], **options: bool) -> None:
        self._repository.set_channel_group(channel_id, server_ids, **options)

    def unmap_group(self, channel_id: str) -> bool:
        return self._repository.remove_channel_group(channel_id)
