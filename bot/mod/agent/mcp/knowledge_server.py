"""
bot/mod/agent/mcp/knowledge_server.py
Modification():
- Expose only public Knowledge retrieval through the official MCP v2 SDK.
- Never expose raw SQLite, filesystem operations or user-private memory.
"""
from __future__ import annotations

from typing import Any


def create_knowledge_server(services: Any):
    from mcp.server import MCPServer

    server = MCPServer("Discord Bot Knowledge")

    @server.tool()
    async def knowledge_search(query: str, limit: int = 6) -> list[dict[str, str]]:
        """Search owner-managed, verified public knowledge chunks."""
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 20:
            raise ValueError("Invalid public knowledge query")
        hits = await services.search_knowledge(query, limit=limit)
        return [
            {"chunk_id": hit.chunk.chunk_id, "source_file": hit.chunk.source_id,
             "content": hit.chunk.content}
            for hit in hits
        ]

    @server.tool()
    def knowledge_read_chunk(chunk_id: str) -> dict[str, str]:
        """Read a known, verified public knowledge chunk by its opaque ID."""
        if not chunk_id.strip() or len(chunk_id) > 128:
            raise ValueError("Invalid chunk id")
        chunk = services.read_knowledge_chunk(chunk_id)
        return {} if chunk is None else {
            "chunk_id": chunk.chunk_id,
            "source_file": chunk.source_id,
            "content": chunk.content,
        }

    @server.tool()
    def knowledge_list_sources(limit: int = 50) -> list[dict[str, str]]:
        """List public knowledge source IDs and titles without private data."""
        if not 1 <= limit <= 100:
            raise ValueError("Invalid source limit")
        return [
            {"source_id": source_id, "title": title}
            for source_id, title in services.list_knowledge_sources(limit=limit)
        ]

    return server
