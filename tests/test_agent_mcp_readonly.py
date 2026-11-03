"""
tests/test_agent_mcp_readonly.py
Modification():
- Verify official MCP protocol exposes only approved read-only Knowledge tools.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mcp import Client

from bot.mod.agent.mcp import MCPKnowledgeClient, create_knowledge_server


@dataclass(frozen=True)
class _Chunk:
    chunk_id: str = "knowledge_test"
    source_id: str = "test.md"
    content: str = "public information"


@dataclass(frozen=True)
class _Hit:
    chunk: _Chunk = _Chunk()


class _Services:
    async def search_knowledge(self, query, *, limit):
        assert query == "minecraft" and limit == 5
        return (_Hit(),)

    def read_knowledge_chunk(self, chunk_id):
        return _Chunk() if chunk_id == "knowledge_test" else None

    def list_knowledge_sources(self, *, limit):
        assert limit == 50
        return (("test.md", "Test"),)


def test_official_mcp_exposes_only_readonly_knowledge_tools() -> None:
    async def run():
        async with Client(create_knowledge_server(_Services())) as client:
            tools = await client.list_tools()
            assert {item.name for item in tools.tools} == {
                "knowledge_search", "knowledge_read_chunk", "knowledge_list_sources",
            }
            result = await client.call_tool("knowledge_search", {"query": "minecraft", "limit": 5})
            assert result.is_error is False
            assert result.structured_content["result"][0]["source_file"] == "test.md"
    asyncio.run(run())


def test_mcp_adapter_round_trip() -> None:
    async def run():
        adapter = MCPKnowledgeClient(_Services())
        hits = await adapter.search("minecraft", limit=5)
        assert hits[0]["chunk_id"] == "knowledge_test"
        chunk = await adapter.read_chunk("knowledge_test")
        assert chunk["content"] == "public information"
        assert await adapter.read_chunk("missing") is None
        sources = await adapter.list_sources()
        assert sources == ({"source_id": "test.md", "title": "Test"},)
    asyncio.run(run())
