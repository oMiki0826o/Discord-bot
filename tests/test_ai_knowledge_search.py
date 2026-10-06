"""
tests/test_ai_knowledge_search.py

Modification():

- 提供 test ai knowledge search 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.knowledge.service import KnowledgeDocument, KnowledgeService
from bot.mod.ai.retrieval.service import HybridRetrievalService


def test_knowledge_search_expands_chinese_server_entry_point_terms(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = KnowledgeService(database)
    service.index(
        KnowledgeDocument(
            source_id="minecraft/net/minecraft/server/Main.java",
            title="minecraft/net/minecraft/server/Main.java",
            content="public static void main(String[] args) {}",
            origin="minecraft source",
        ),
        now=1,
    )

    hits = service.search("伺服器啟動程式", limit=3)

    assert [hit.chunk.source_id for hit in hits] == ["minecraft/net/minecraft/server/Main.java"]


def test_knowledge_search_expands_english_server_startup_terms(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = KnowledgeService(database)
    service.index(
        KnowledgeDocument(
            source_id="minecraft/net/minecraft/server/Main.java",
            title="minecraft/net/minecraft/server/Main.java",
            content="public static void main(String[] args) {}",
            origin="minecraft source",
        ),
        now=1,
    )

    hits = service.search("Minecraft server startup program Java file", limit=3)

    assert [hit.chunk.source_id for hit in hits] == ["minecraft/net/minecraft/server/Main.java"]


def test_knowledge_search_handles_traditional_simplified_cjk_and_separated_terms(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = KnowledgeService(database)
    service.index(
        KnowledgeDocument(
            source_id="wiki/update-suppression.md",
            title="更新抑制",
            # Real Wiki markup and punctuation can split terms that a user's
            # natural-language query writes as one uninterrupted CJK phrase.
            content="类型 转换异常 可造成 更新 抑制。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )

    hits = service.search("類型轉換異常與更新抑制", limit=3)

    assert [hit.chunk.source_id for hit in hits] == ["wiki/update-suppression.md"]


def test_knowledge_search_prioritizes_matching_article_title_for_natural_question(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = KnowledgeService(database)
    service.index(
        KnowledgeDocument(
            source_id="wiki/oxidation.md",
            title="氧化",
            content=(
                "铜质方块会随时间逐渐氧化。"
                "周围没有氧化程度更低的铜质方块时，才有机会进入下一阶段。"
            ),
            origin="Minecraft Wiki",
        ),
        now=1,
    )
    service.index(
        KnowledgeDocument(
            source_id="wiki/chat-log.md",
            title="玩家留言",
            content="銅要怎麼曬才會氧化？這是玩家未驗證的問句。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )

    hits = service.search("銅要怎麼曬才會氧化", limit=2)

    assert hits[0].chunk.source_id == "wiki/oxidation.md"


def test_knowledge_search_marks_direct_title_overlap(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = KnowledgeService(database)
    service.index(
        KnowledgeDocument(
            source_id="wiki/oxidation.md",
            title="氧化",
            content="铜质方块会随时间逐渐氧化。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )

    hit = service.search("銅要怎麼曬才會氧化", limit=1)[0]

    assert hit.title_match > 0


def test_knowledge_search_matches_a_namespaced_title_segment(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    service = KnowledgeService(database)
    service.index(
        KnowledgeDocument(
            source_id="wiki/zombie-reinforcement.md",
            title="屬性/僵屍增援",
            content="僵屍受到攻擊時可能嘗試生成增援。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )

    hit = service.search("僵屍增援的生成條件是什麼", limit=1)[0]

    assert hit.title_match >= len("僵屍增援")


def test_hybrid_retrieval_drops_unmatched_noise_when_an_article_title_matches(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    knowledge = KnowledgeService(database)
    knowledge.index(
        KnowledgeDocument(
            source_id="wiki/oxidation.md",
            title="氧化",
            content="单独放置的铜质方块氧化速度最快。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )
    knowledge.index(
        KnowledgeDocument(
            source_id="wiki/changelog.md",
            title="Java 版更新",
            content="銅要怎麼曬才會氧化？這是無關的留言。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )
    retrieval = HybridRetrievalService(
        knowledge=knowledge,
        vectors=object(),
        embedder=None,
    )

    hits = asyncio.run(retrieval.search_knowledge("銅要怎麼曬才會氧化", limit=6))

    assert [hit.chunk.source_id for hit in hits] == ["wiki/oxidation.md"]


def test_title_match_does_not_promote_generic_parenthetical_disambiguation(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    knowledge = KnowledgeService(database)
    knowledge.index(
        KnowledgeDocument(
            source_id="wiki/unrelated.md",
            title="為什麼會變成這樣呢？（方塊）/顯示",
            content="方塊顯示效果。",
            origin="Minecraft Wiki",
        ),
        now=1,
    )

    hit = knowledge.search("如何讓銅方塊快點變綠", limit=1)[0]

    assert hit.title_match == 0
