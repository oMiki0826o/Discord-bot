"""Regression specifications for Discord AI safety and real token accounting."""
from __future__ import annotations

import asyncio

from bot.mod.ai.commands.mention_gate import parse_direct_mention
from bot.mod.ai.commands.message_render import render_footer
from bot.mod.ai.provider.models import ProviderResponse, TokenUsage
from bot.mod.ai.runtime.basic import BasicRuntime
from bot.mod.ai.runtime.models import RuntimeRequest
from bot.mod.ai.search.cache import SearchCache


def test_direct_mention_accepts_only_explicit_bot_address() -> None:
    bot = 12345678901234567
    assert parse_direct_mention(f"<@{bot}> 你好", bot) == "你好"
    assert parse_direct_mention(f"<@!{bot}> 你好", bot) == "你好"
    for message in (
        "@everyone 你好", "@here 你好", "<@&12345678901234567> 你好",
        f"你好 <@{bot}>", f"> <@{bot}> 你好",
        f"```<@{bot}> 你好```", f"<@{bot + 1}> 你好",
    ):
        assert parse_direct_mention(message, bot) is None


def test_footer_shows_separate_actual_input_and_output_tokens() -> None:
    from bot.mod.ai.runtime.models import RuntimeResult, RuntimeStopReason
    result = RuntimeResult("你好", RuntimeStopReason.COMPLETED, 1, 0, 2000, "gemini-test",
                           usage=TokenUsage(120, 45, 175, 10))
    footer = render_footer(result)
    assert footer.startswith("-# ")
    assert "輸入 120" in footer
    assert "輸出 45" in footer
    assert "思考 10" in footer
    assert "2.0s" in footer


def test_footer_never_invents_provider_tokens() -> None:
    from bot.mod.ai.runtime.models import RuntimeResult, RuntimeStopReason
    result = RuntimeResult("你好", RuntimeStopReason.COMPLETED, 1, 0, 900, "gemini-test")
    footer = render_footer(result)
    assert "輸入 —" in footer
    assert "輸出 —" in footer
    assert "tok/s" not in footer


def test_cache_isolation_by_user_and_context() -> None:
    class Provider:
        def __init__(self):
            self.calls = 0

        async def generate(self, request):
            self.calls += 1
            from bot.mod.ai.provider.models import ProviderObservation
            return ProviderResponse(f"private output {self.calls}", "test",
                                    observation=ProviderObservation(grounded=True),
                                    usage=TokenUsage(11, 2, 13))

    provider = Provider()
    runtime = BasicRuntime(provider, max_output_tokens=200, timeout_seconds=2,
                           retries_per_model=1, search_cache=SearchCache(), now=lambda: 100)
    def make(user, context):
        return RuntimeRequest(request_id="id", user_id=user, channel_id="channel",
                              prompt="請解釋活塞更新", context_blocks=(context,),
                              system_instruction="system", model_candidates=("test",),
                              capabilities=frozenset({"web"}))

    async def run():
        first = await runtime.run(make("alice", "private-a"))
        repeat = await runtime.run(make("alice", "private-a"))
        other = await runtime.run(make("bob", "private-a"))
        updated = await runtime.run(make("alice", "private-b"))
        return first, repeat, other, updated

    first, repeat, other, updated = asyncio.run(run())
    assert first.text == repeat.text
    assert first.text != other.text
    assert first.text != updated.text
    assert provider.calls == 3
    assert first.usage == TokenUsage(11, 2, 13)


def test_near_duplicate_queries_are_not_equivalent() -> None:
    from bot.mod.ai.search.cache import SearchObservation
    cache = SearchCache()
    cache.put("台北今天的天氣", SearchObservation("晴", True), now=100)
    assert cache.get("台中今天的天氣", now=101) is None
