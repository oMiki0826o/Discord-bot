"""
bot/mod/agent/builtin_tools.py

Modification():

- 將 AI public facade 的 Memory、Profile、History、Topic、Knowledge 與 Channel Context 接成只讀 Tools。
- 將 Agent-owned Skills 接成 progressive-loading Tools。
- 使用具名欄位需求 helper，讓 Tool schema 建立保持可讀與可檢查。

所有 private scope 都來自 trusted RuntimeRequest。
"""

from __future__ import annotations

from typing import Any

from .tools import Tool, ToolContext, ToolRegistry


def build_readonly_registry(services: Any, *, skills: Any = None) -> ToolRegistry:
    registry = ToolRegistry()

    async def search_memory(arguments, context: ToolContext):
        return await services.search_requester_memory(context.request, str(arguments["query"]), limit=20)

    async def read_profile(arguments, context: ToolContext):
        return services.read_public_profile(str(arguments["target_user_id"]))

    async def search_profiles(arguments, context: ToolContext):
        matches = services.search_public_profiles(str(arguments["query"]), limit=10)
        return tuple({"user_id": user_id, "profile": profile} for user_id, profile in matches)

    async def search_history(arguments, context: ToolContext):
        hits = services.search_history(context.request, str(arguments["query"]), limit=10)
        return tuple({"event_id": hit.event.event_id, "role": hit.event.role.value, "content": hit.event.content, "created_at": hit.event.created_at} for hit in hits)

    async def read_topics(arguments, context: ToolContext):
        topics = services.read_topics(context.request)
        return tuple({"name": item.name, "status": item.status.value, "current_goal": item.current_goal, "state": item.state} for item in topics)

    async def search_knowledge(arguments, context: ToolContext):
        hits = await services.search_knowledge(str(arguments["query"]), limit=6)
        return tuple({
            "chunk_id": hit.chunk.chunk_id,
            "source_file": hit.chunk.source_id,
            "content": hit.chunk.content,
        } for hit in hits)

    async def read_chunk(arguments, context: ToolContext):
        chunk = services.read_knowledge_chunk(str(arguments["chunk_id"]))
        return None if chunk is None else {
            "chunk_id": chunk.chunk_id,
            "source_file": chunk.source_id,
            "content": chunk.content,
        }

    async def read_channel(arguments, context: ToolContext):
        return await services.read_channel_context(context.request, str(arguments["query"]))

    async def current_time(arguments, context: ToolContext):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        return {"timezone": "Asia/Taipei", "iso": now.isoformat(), "display": now.strftime("%Y-%m-%d %H:%M:%S")}

    def required(name: str) -> frozenset[str]:
        return frozenset({name})
    registry.register(Tool("search_user_memory", "Search the requester's private long-term memory", "memory", required("query"), search_memory, required("query")))
    registry.register(Tool("read_public_profile", "Read explicitly public profile fields for a user", "public_profile", required("target_user_id"), read_profile, required("target_user_id")))
    registry.register(Tool("search_public_profiles", "Search explicitly public profiles by name or content", "public_profile", required("query"), search_profiles, required("query")))
    registry.register(Tool("search_history", "Search requester history in the current channel", "history", required("query"), search_history, required("query")))
    registry.register(Tool("read_topics", "Read requester project/topic state in the current channel", "topic", frozenset(), read_topics))
    registry.register(Tool(
        "search_knowledge",
        "Search owner-indexed knowledge. Use this before answering factual or mechanism questions about Minecraft or indexed source code; do not rely on model memory. Search concise canonical concepts rather than copying the whole colloquial question, and retry with a synonym or likely English identifiers when results are unrelated. For source-code questions, translate concepts to likely class, method, or field names.",
        "knowledge",
        required("query"),
        search_knowledge,
        required("query"),
        retry_on_empty=True,
    ))
    registry.register(Tool("read_knowledge_chunk", "Read one known knowledge chunk", "knowledge", required("chunk_id"), read_chunk, required("chunk_id")))
    registry.register(Tool("read_channel_context", "Read visible context from the current channel", "channel_context", required("query"), read_channel, required("query")))
    registry.register(Tool("current_time", "Read the current time in Asia/Taipei", "time", frozenset(), current_time))

    if skills is not None:
        async def list_skills(arguments, context: ToolContext):
            return tuple({"name": item.name, "summary": item.summary, "when_to_use": item.when_to_use} for item in skills.list_skills())

        async def read_skill(arguments, context: ToolContext):
            item = skills.read_skill(str(arguments["name"]))
            return {"name": item.name, "content": item.content}

        registry.register(Tool("list_skills", "List available skill metadata", "skills", frozenset(), list_skills))
        registry.register(Tool("read_skill", "Read one selected skill", "skills", required("name"), read_skill, required("name")))

    return registry
