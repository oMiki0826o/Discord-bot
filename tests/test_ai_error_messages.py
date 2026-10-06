"""
tests/test_ai_error_messages.py

Modification():

- 提供 test ai error messages 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from bot.mod.ai.commands.discord import build_discord_identity_context, dashboard_operational_summary, user_error_message
from bot.mod.ai.service import render_user_context
from bot.mod.ai.provider.errors import ProviderQuotaError, ProviderVerificationError


def test_search_verification_failure_has_a_specific_user_safe_message() -> None:
    assert "驗證" in user_error_message(ProviderVerificationError("missing grounding"))


def test_quota_failure_has_a_specific_user_safe_message() -> None:
    assert "額度" in user_error_message(ProviderQuotaError("quota"))


def test_discord_identity_context_marks_unknown_mentions_without_guessing() -> None:
    context = build_discord_identity_context(
        "hello <@1> <@!2>", author_id="1", bot_user_id="9", known_members={"2": "Alice"},
    )

    assert "current_user" in context
    assert "member=Alice" in context
    assert "unknown" not in context


def test_dashboard_operational_summary_only_renders_aggregate_values() -> None:
    assert dashboard_operational_summary({"token_estimate": 1234, "provider_errors": 2}) == "Estimated tokens: 1,234\nProvider errors: 2"


def test_user_context_renderer_uses_only_known_profile_fields() -> None:
    assert render_user_context({"tier": 2, "tier_name": "朋友", "interaction_count": 8, "mode": "creative", "mode_label": "創意寫作", "secret": "ignore"}) == "Requester AI profile (reference only): tier=2 (朋友), interactions=8, mode=creative (創意寫作)"


def test_user_context_renderer_marks_only_a_trusted_important_person() -> None:
    assert "relationship=important_person" in render_user_context({"relationship": "important_person"})
    assert "relationship=" not in render_user_context({"relationship": "untrusted input"})
