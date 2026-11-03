"""
bot/mod/agent/mcp/client.py
Modification():
- Invoke public Knowledge tools over official MCP in-process transport.
- Fail closed on tool errors; return only typed, bounded data.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .knowledge_server import create_knowledge_server


class MCPKnowledgeClient:
    """Local MCP transport: no port, shell, arbitrary SQL, or user-selected host."""

    def __init__(self, services: Any) -> None:
        self.server = create_knowledge_server(services)

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        from mcp import Client

        async with asyncio.timeout(9.0):
            async with Client(self.server) as client:
                response = await client.call_tool(name, arguments)
                if response.is_error or response.structured_content is None:
                    raise ValueError("MCP knowledge query failed")
                return response.structured_content

    async def search(self, query: str, *, limit: int = 6) -> tuple[dict[str, str], ...]:
        result = await self._call("knowledge_search", {"query": query, "limit": limit})
        items = result.get("result", []) if isinstance(result, dict) else result
        return tuple(items)

    async def read_chunk(self, chunk_id: str) -> dict[str, str] | None:
        result = await self._call("knowledge_read_chunk", {"chunk_id": chunk_id})
        item = result.get("result", result) if isinstance(result, dict) else result
        return item or None

    async def list_sources(self, *, limit: int = 50) -> tuple[dict[str, str], ...]:
        result = await self._call("knowledge_list_sources", {"limit": limit})
        items = result.get("result", []) if isinstance(result, dict) else result
        return tuple(items)
