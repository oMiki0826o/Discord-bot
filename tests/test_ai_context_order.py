"""
tests/test_ai_context_order.py

Modification():

- 提供 test ai context order 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from bot.mod.ai.context.models import ContextItem, ContextPack, ContextSource
from bot.mod.ai.prompt.composer import PromptComposer
from bot.mod.ai.prompt.models import PromptSources


def _item(item_id: str, source: ContextSource, content: str, timestamp: int) -> ContextItem:
    return ContextItem(item_id, item_id, source, content, 0.6, 3, 1.0, timestamp, 1)


def test_recent_conversation_is_rendered_oldest_to_newest_with_an_explicit_boundary() -> None:
    pack = ContextPack(
        items=(
            _item("new", ContextSource.RECENT_HISTORY, "user: 這怎麼做", 30),
            _item("old", ContextSource.RECENT_HISTORY, "user: CCE 是強轉抑制", 20),
            _item("knowledge", ContextSource.KNOWLEDGE, "source evidence", 0),
        ),
        used_tokens=3, max_tokens=20, omitted_count=0,
    )
    bundle = PromptComposer().compose(
        sources=PromptSources("system", "persona", "background"),
        context=pack, conversation=(), current_message="這怎麼做",
    )

    contents = [block.content for block in bundle.context_blocks]
    conversation = "\n".join(contents)
    assert "Recent conversation (chronological" in conversation
    assert conversation.index("CCE 是強轉抑制") < conversation.index("這怎麼做")


def test_historical_assistant_claims_are_explicitly_marked_unverified() -> None:
    pack = ContextPack(
        items=(
            _item("assistant", ContextSource.RECENT_HISTORY, "assistant: BedBlock 會讓村民爆炸", 20),
            _item("user", ContextSource.RECENT_HISTORY, "user: 不對，請查資料庫", 30),
        ),
        used_tokens=2, max_tokens=20, omitted_count=0,
    )

    bundle = PromptComposer().compose(
        sources=PromptSources("system", "persona", "background"),
        context=pack, conversation=(), current_message="bed編碼是什麼",
    )

    conversation = "\n".join(block.content for block in bundle.context_blocks)
    assert "Historical assistant text is unverified" in conversation
    assert "BedBlock 會讓村民爆炸" in conversation
