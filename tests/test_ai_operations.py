"""
tests/test_ai_operations.py

Modification():

- AI Owner operations keep access control and diagnostics content-safe.
- 維護 test ai operations 的發布版行為與驗證契約。
"""

from __future__ import annotations

import asyncio

import pytest

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.guard import GuardRejectedError, RequestGuard
from bot.mod.ai.operations import AiOperations


def test_banned_user_is_rejected_by_request_guard(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    operations = AiOperations(database, now=lambda: 100)
    operations.ban("user-a", actor_id="owner", reason="abuse")
    guard = RequestGuard(
        cooldown_seconds=0,
        abuse_limit=3,
        abuse_window_seconds=60,
        is_blocked=operations.block_reason,
    )

    with pytest.raises(GuardRejectedError, match="banned"):
        asyncio.run(guard.acquire("user-a", prompt="hello"))


def test_diagnostics_and_audit_never_return_free_form_content(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    operations = AiOperations(database, now=lambda: 100)
    operations.ban("user-a", actor_id="owner", reason="secret prompt text")

    result = operations.diagnose("database")
    audit = operations.audit()

    assert result["schema_version"] >= 6
    assert "secret prompt text" not in str(result)
    assert audit[0]["action"] == "access.ban"
    assert "secret prompt text" not in str(audit)


def test_memory_operations_require_target_and_forget_is_non_destructive(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO memories (memory_id, user_id, scope_type, scope_id, memory_type, memory_key, value_json, confidence, importance, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("mem-a", "user-a", "global", "user-a", "preference", "language", '"zh-TW"', 1.0, 5, "active", 1, 1),
        )
    operations = AiOperations(database, now=lambda: 100)

    assert [item["memory_id"] for item in operations.list_memories("user-a")] == ["mem-a"]
    with pytest.raises(KeyError):
        operations.show_memory("user-b", "mem-a")
    assert operations.forget_memory("user-a", "mem-a", actor_id="owner") is True
    assert operations.show_memory("user-a", "mem-a")["status"] == "rejected"


def test_memory_evidence_and_history_exports_are_target_scoped(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute("INSERT INTO events (event_id, user_id, channel_id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("evt-a", "user-a", "channel", "conv", "user", "original evidence", 1))
        connection.execute("INSERT INTO events (event_id, user_id, channel_id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("evt-b", "user-b", "channel", "conv", "user", "private other user", 1))
        connection.execute("INSERT INTO memory_candidates (candidate_id, source_event_id, user_id, scope_type, scope_id, memory_type, memory_key, value_json, confidence, importance, assertion_strength, temporal_scope, status, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("candidate-a", "evt-a", "user-a", "global", "user-a", "preference", "language", '"zh-TW"', 1.0, 5, "explicit", "permanent", "accepted", 1))
        connection.execute("INSERT INTO memories (memory_id, user_id, scope_type, scope_id, memory_type, memory_key, value_json, confidence, importance, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("mem-a", "user-a", "global", "user-a", "preference", "language", '"zh-TW"', 1.0, 5, "active", 1, 1))
        connection.execute("INSERT INTO memory_evidence (memory_id, event_id, candidate_id, relation, created_at) VALUES (?, ?, ?, ?, ?)", ("mem-a", "evt-a", "candidate-a", "supporting", 1))
    operations = AiOperations(database)

    assert operations.memory_evidence("user-a", "mem-a")[0]["event_id"] == "evt-a"
    assert "original evidence" in operations.export_history("user-a")
    assert "private other user" not in operations.export_history("user-a")


def test_dashboard_snapshot_is_aggregate_only_and_groups_models(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db"); database.initialize()
    with database.transaction() as connection:
        connection.execute("INSERT INTO events (event_id, user_id, channel_id, conversation_id, role, content, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("a", "user-a", "chan", "conv", "assistant", "private text", 100, '{"model":"gemini-test"}'))
    snapshot = AiOperations(database, now=lambda: 200).dashboard_snapshot(hours=24)

    assert snapshot["requests_24h"] == 1
    assert snapshot["active_users"] == 1
    assert snapshot["by_model"] == {"gemini-test": 1}
    assert "private text" not in str(snapshot)


def test_usage_telemetry_is_aggregated_without_storing_prompt_content(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db"); database.initialize()
    operations = AiOperations(database, now=lambda: 100)
    operations.record_usage("user-a", "gemini-test", "private prompt", "private response")
    operations.record_error("user-a", "gemini-test", "timeout")

    snapshot = operations.dashboard_snapshot(hours=24)

    assert snapshot["token_estimate"] > 0
    assert snapshot["provider_errors"] == 1
    assert "private prompt" not in str(snapshot)




def test_ai_operational_tables_are_created_by_the_schema_migration(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()

    with database.connect() as connection:
        migrations = {
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert 11 in migrations
    assert {"search_cache", "ai_usage", "ai_provider_errors", "ai_data_manifest", "ai_user_state", "ai_provider_traces"} <= tables


def test_user_tier_interactions_and_temporary_mode_are_ai_module_owned(tmp_path) -> None:
    now = [100]
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    operations = AiOperations(database, now=lambda: now[0])

    operations.set_tier("user-a", 3, actor_id="owner")
    assert operations.record_interaction("user-a") == 1
    operations.set_mode("user-a", "creative", ttl_minutes=1, actor_id="owner")

    assert operations.user_context("user-a") == {
        "tier": 3,
        "tier_name": "開拓者",
        "interaction_count": 1,
        "mode": "creative",
        "mode_label": "創意寫作",
        "relationship": "standard",
    }
    now[0] = 161
    assert operations.user_context("user-a")["mode"] == "normal"


def test_owner_is_exposed_as_the_trusted_important_person_only(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    operations = AiOperations(database, owner_id="owner-id")

    assert operations.user_context("owner-id")["relationship"] == "important_person"
    assert operations.user_context("member-id")["relationship"] == "standard"


def test_memory_export_includes_owner_visible_value_and_evidence_count(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute("INSERT INTO events (event_id, user_id, channel_id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("event", "user-a", "channel", "conversation", "user", "source", 1))
        connection.execute("INSERT INTO memory_candidates (candidate_id, source_event_id, user_id, scope_type, scope_id, memory_type, memory_key, value_json, confidence, importance, assertion_strength, temporal_scope, status, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("candidate", "event", "user-a", "global", "user-a", "preference", "drink", '"tea"', 1.0, 4, "explicit", "permanent", "accepted", 1))
        connection.execute("INSERT INTO memories (memory_id, user_id, scope_type, scope_id, memory_type, memory_key, value_json, confidence, importance, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("memory", "user-a", "global", "user-a", "preference", "drink", '"tea"', 1.0, 4, "active", 1, 1))
        connection.execute("INSERT INTO memory_evidence (memory_id, event_id, candidate_id, relation, created_at) VALUES (?, ?, ?, ?, ?)", ("memory", "event", "candidate", "supporting", 1))

    output = AiOperations(database).export_memories("user-a")

    assert "# AI Memory Export: user-a" in output
    assert "Value: `tea`" in output
    assert "Evidence records: 1" in output


def test_provider_trace_is_content_free_and_keeps_fallback_chain(tmp_path) -> None:
    database = AiDatabase(tmp_path / "ai.db")
    database.initialize()
    operations = AiOperations(database, now=lambda: 100)

    operations.record_provider_trace("request-a", "user-a", "flash", "quota")
    operations.record_provider_trace("request-a", "user-a", "gemini", "success")

    assert operations.provider_trace("request-a") == (
        {"model": "flash", "outcome": "quota", "created_at": 100},
        {"model": "gemini", "outcome": "success", "created_at": 100},
    )
    assert operations.recent_provider_traces(limit=1) == (
        {"request_id": "request-a", "model": "gemini", "outcome": "success", "created_at": 100},
    )
