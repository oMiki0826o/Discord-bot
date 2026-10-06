"""bot/mod/dmcc/services/autocomplete.py
Delegate Minecraft command suggestions to the authoritative Brigadier server.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from typing import Protocol


class AutocompleteRequester(Protocol):
    async def request(self, server_id: str, packet_type: str, data: dict[str, object]) -> dict[str, object]: ...


class AutocompleteService:
    """A small protocol service with no Discord or Minecraft API dependency."""

    def __init__(self, requester: AutocompleteRequester) -> None:
        self._requester = requester

    async def suggest(self, server_id: str, command_input: str, *, op_level: int = 0) -> tuple[str, ...]:
        """Request suggestions visible to the caller's delegated Minecraft OP level."""

        if not isinstance(command_input, str) or not command_input.strip():
            return ()
        if type(op_level) is not int:
            raise ValueError("op_level must be an integer")
        response = await self._requester.request(
            server_id,
            "autocomplete_request",
            {"input": command_input, "op_level": max(0, min(4, op_level))},
        )
        values = response.get("suggestions", [])
        if not isinstance(values, list):
            return ()
        return tuple(value for value in values if isinstance(value, str))
