"""
tests/test_ai_routing.py

Modification():

- 驗證 Agent web tool turn 會選用設定中的 Gemini 3+ 專用模型池。
- 驗證一般模型路由與 slash selector 契約保持一致。
"""

from __future__ import annotations

import asyncio

from bot.mod.ai.api import AiServices
from bot.mod.ai.config import AiSettings, DEFAULT_SETTINGS, model_selector_choices
from bot.mod.ai.commands.discord import apply_model_selection
from bot.mod.ai.provider.models import ProviderResponse
from bot.mod.ai.routing import RouteRequest, Router, extract_model_directive
from bot.mod.ai.runtime.models import RuntimeRequest


def test_case_insensitive_directive_is_removed_before_routing() -> None:
    selected, prompt = extract_model_directive("使用 FLASH 幫我查最新天氣")

    assert selected == "flash"
    assert prompt == "幫我查最新天氣"
    decision = Router().route(RouteRequest(prompt=prompt, model_override=selected))
    assert decision.model_category == "web"


def test_model_selector_choices_match_configured_route_categories() -> None:
    settings = AiSettings.from_mapping(DEFAULT_SETTINGS)

    assert model_selector_choices(settings) == (
        ("Gemini", "gemini"),
        ("Flash", "flash"),
        ("Gemma", "gemma"),
        ("Agent", "agent"),
    )


def test_settings_schema_accepts_the_gemma_fallback_pool() -> None:
    settings = AiSettings.from_mapping(DEFAULT_SETTINGS)

    assert settings.model_pools["gemma"]


def test_default_pools_preserve_the_legacy_full_fallback_order() -> None:
    settings = AiSettings.from_mapping(DEFAULT_SETTINGS)

    assert settings.default_model == "gemini-3.1-flash-lite"
    assert settings.model_pools["chat"] == (
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
    )
    assert settings.model_pools["web"] == (
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
    )
    assert settings.model_pools["agent_web"] == (
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
    )


def test_agent_web_turn_uses_the_configured_gemini_3_combined_tool_pool() -> None:
    class _Provider:
        def __init__(self) -> None:
            self.request = None

        async def generate(self, request):
            self.request = request
            return ProviderResponse("done", "gemini-3-flash-preview")

    provider = _Provider()
    request = RuntimeRequest(
        request_id="request", user_id="user", channel_id="channel", prompt="latest weather",
        model_candidates=("gemini-2.5-flash",), capabilities=frozenset({"web", "knowledge"}),
    )

    asyncio.run(AiServices(
        _provider=provider,
        _settings=AiSettings.from_mapping(DEFAULT_SETTINGS),
    ).generate_model_turn(request, (), ({"name": "search_knowledge"},), allow_tools=True))

    assert provider.request.model_candidates == (
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
    )
    assert provider.request.allow_combined_tools is True


def test_route_uses_chat_pool_for_gemini_and_web_pool_for_flash() -> None:
    router = Router()

    assert router.route(RouteRequest(prompt="hello", model_override="gemini")).model_category == "chat"
    assert router.route(RouteRequest(prompt="hello", model_override="flash")).model_category == "web"


def test_slash_model_selection_uses_the_same_directive_contract() -> None:
    selected, prompt = extract_model_directive(apply_model_selection("幫我摘要", "GemMa"))

    assert selected == "gemma"
    assert prompt == "幫我摘要"


def test_minecraft_mechanism_questions_prefetch_indexed_knowledge() -> None:
    route = Router().infer("bed編碼是什麼")

    assert route.wants_knowledge is True


def test_technical_how_to_question_prefetches_indexed_knowledge() -> None:
    route = Router().infer("怎麼做更新抑制器")

    assert route.wants_knowledge is True
