"""
tests/test_ai_search_cache.py

Modification():

- 提供 test ai search cache 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import asyncio

from bot.mod.ai.search.cache import SearchCache, SearchObservation
from bot.mod.ai.database import AiDatabase
from bot.mod.ai.provider.models import ProviderObservation, ProviderResponse
from bot.mod.ai.runtime.basic import BasicRuntime
from bot.mod.ai.runtime.models import RuntimeRequest


def test_exact_search_hit_expires_after_short_ttl() -> None:
    cache = SearchCache(short_ttl_seconds=60, long_ttl_seconds=600)
    observation = SearchObservation(text="Taipei weather", success=True, stable=False)

    cache.put("Taipei weather", observation, now=100)

    assert cache.get("Taipei weather", now=159) == observation
    assert cache.get("Taipei weather", now=160) is None


def test_fuzzy_search_hit_normalizes_case_and_whitespace() -> None:
    cache = SearchCache(short_ttl_seconds=60, long_ttl_seconds=600)
    observation = SearchObservation(text="result", success=True, stable=True)

    cache.put("  Latest   Taiwan News ", observation, now=100)

    assert cache.get("latest taiwan news", now=699) == observation


def test_fuzzy_search_hit_reuses_near_duplicate_query() -> None:
    cache = SearchCache(short_ttl_seconds=60, long_ttl_seconds=600, fuzzy_threshold=0.8)
    observation = SearchObservation(text="result", success=True, stable=True)

    cache.put("latest taiwan technology news", observation, now=100)

    assert cache.get("latest taiwan tech news", now=200) == observation


def test_sqlite_search_cache_survives_a_new_cache_instance(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    observation = SearchObservation(text="verified", success=True, stable=True)

    SearchCache(database=database).put("query", observation, now=100)

    assert SearchCache(database=database).get("query", now=101) == observation


def test_failed_or_empty_search_is_never_cached() -> None:
    cache = SearchCache()

    cache.put("query", SearchObservation(text="", success=True), now=100)
    cache.put("query", SearchObservation(text="error", success=False), now=100)

    assert cache.get("query", now=100) is None


def test_search_cache_status_exposes_hits_and_misses() -> None:
    cache = SearchCache()
    observation = SearchObservation(text="verified", success=True)

    assert cache.get("missing", now=100) is None
    cache.put("query", observation, now=100)
    assert cache.get("query", now=101) == observation

    assert cache.status(now=101) == {
        "entries": 1,
        "expired": 0,
        "hits": 1,
        "misses": 1,
    }


def test_verified_web_response_is_reused_from_cache() -> None:
    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request, model=None):
            self.calls += 1
            return ProviderResponse("verified result", "model", observation=ProviderObservation(grounded=True))

    provider = Provider()
    runtime = BasicRuntime(
        provider,
        max_output_tokens=10,
        timeout_seconds=1,
        retries_per_model=1,
        search_cache=SearchCache(),
        now=lambda: 100,
    )
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="latest weather",
        system_instruction="system", model_candidates=("model",), capabilities=frozenset({"web"}),
    )

    async def run() -> tuple[object, object]:
        return await runtime.run(request), await runtime.run(request)

    first, second = asyncio.run(run())

    assert first.text == second.text == "verified result"
    assert provider.calls == 1
