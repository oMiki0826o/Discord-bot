"""
bot/mod/ai/operations.py

Modification():

- Owner-facing, content-safe AI operational data services。
"""

from __future__ import annotations

import time
import json
from collections.abc import Callable
from typing import Any

from .database import AiDatabase
from .provider.models import TokenUsage

_TIER_NAMES = {0: "陌生人", 1: "路人", 2: "朋友", 3: "開拓者"}
_MODE_LABELS = {
    "normal": "一般對話", "roleplay": "角色扮演", "creative": "創意寫作",
    "task": "任務模式", "debate": "辯論模式",
}


class AiOperations:
    def __init__(
        self,
        database: AiDatabase,
        *,
        now: Callable[[], int] | None = None,
        owner_id: str | None = None,
    ) -> None:
        self._database = database
        self._now = now or (lambda: int(time.time()))
        self._owner_id = owner_id.strip() if owner_id and owner_id.strip() else None

    def record_usage(self, user_id: str, model: str, prompt: str, response: str) -> None:
        """Compatibility entry point for callers without provider metadata."""

        usage = TokenUsage(
            max(1, len(prompt) // 3),
            max(1, len(response) // 3),
            max(1, len(prompt) // 3) + max(1, len(response) // 3),
            estimated=True,
        )
        self.record_provider_usage(user_id, model, usage)

    def record_provider_usage(self, user_id: str, model: str, usage: TokenUsage) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO ai_usage (user_id, model, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, model, usage.input_tokens, usage.output_tokens, self._now()),
            )

    def record_error(self, user_id: str, model: str, error_type: str) -> None:
        with self._database.transaction() as connection:
            connection.execute("INSERT INTO ai_provider_errors (user_id, model, error_type, created_at) VALUES (?, ?, ?, ?)", (user_id, model, error_type[:80], self._now()))

    def record_provider_trace(self, request_id: str, user_id: str, model: str, outcome: str) -> None:
        if not all(value.strip() for value in (request_id, user_id, model, outcome)):
            raise ValueError("provider trace fields are required")
        with self._database.transaction() as connection:
            connection.execute("INSERT INTO ai_provider_traces (request_id, user_id, model, outcome, created_at) VALUES (?, ?, ?, ?, ?)", (request_id, user_id, model, outcome[:80], self._now()))

    def provider_trace(self, request_id: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT model, outcome, created_at FROM ai_provider_traces WHERE request_id = ? ORDER BY trace_id LIMIT ?", (request_id, limit)).fetchall()
        return tuple(dict(row) for row in rows)

    def recent_provider_traces(self, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
        if not 1 <= limit <= 100:
            raise ValueError("trace limit must be between 1 and 100")
        with self._database.connect() as connection:
            rows = connection.execute("SELECT request_id, model, outcome, created_at FROM ai_provider_traces ORDER BY trace_id DESC LIMIT ?", (limit,)).fetchall()
        return tuple(dict(row) for row in rows)

    def set_tier(self, user_id: str, tier: int, *, actor_id: str) -> None:
        if not user_id.strip() or not actor_id.strip() or tier not in _TIER_NAMES:
            raise ValueError("invalid user tier")
        now = self._now()
        with self._database.transaction() as connection:
            self._ensure_user_state(connection, user_id, now)
            connection.execute("UPDATE ai_user_state SET tier = ?, updated_at = ? WHERE user_id = ?", (tier, now, user_id))
            self._audit(connection, actor_id, "user.tier.set", user_id, now)

    def record_interaction(self, user_id: str) -> int:
        now = self._now()
        with self._database.transaction() as connection:
            self._ensure_user_state(connection, user_id, now)
            connection.execute("UPDATE ai_user_state SET interaction_count = interaction_count + 1, updated_at = ? WHERE user_id = ?", (now, user_id))
            return int(connection.execute("SELECT interaction_count FROM ai_user_state WHERE user_id = ?", (user_id,)).fetchone()[0])

    def set_mode(self, user_id: str, mode: str, *, ttl_minutes: int, actor_id: str) -> None:
        if not user_id.strip() or not actor_id.strip() or mode not in _MODE_LABELS or ttl_minutes < 0:
            raise ValueError("invalid user mode")
        now = self._now()
        expires_at = None if mode == "normal" or ttl_minutes == 0 else now + ttl_minutes * 60
        with self._database.transaction() as connection:
            self._ensure_user_state(connection, user_id, now)
            connection.execute("UPDATE ai_user_state SET mode = ?, mode_expires_at = ?, updated_at = ? WHERE user_id = ?", (mode, expires_at, now, user_id))
            self._audit(connection, actor_id, "user.mode.set", user_id, now)

    def user_context(self, user_id: str) -> dict[str, Any]:
        with self._database.connect() as connection:
            row = connection.execute("SELECT tier, interaction_count, mode, mode_expires_at FROM ai_user_state WHERE user_id = ?", (user_id,)).fetchone()
        tier = 0 if row is None else int(row["tier"])
        mode = "normal" if row is None or (row["mode_expires_at"] is not None and int(row["mode_expires_at"]) <= self._now()) else str(row["mode"])
        relationship = "important_person" if user_id == self._owner_id else "standard"
        return {
            "tier": tier,
            "tier_name": _TIER_NAMES[tier],
            "interaction_count": 0 if row is None else int(row["interaction_count"]),
            "mode": mode,
            "mode_label": _MODE_LABELS.get(mode, mode),
            "relationship": relationship,
        }

    def ban(self, user_id: str, *, actor_id: str, reason: str = "") -> None:
        self._set_rule(user_id, "banned", actor_id, reason=reason)

    def unban(self, user_id: str, *, actor_id: str) -> bool:
        return self._remove_rule(user_id, "banned", actor_id)

    def unrestrict(self, user_id: str, *, actor_id: str) -> bool:
        return self._remove_rule(user_id, "restricted", actor_id)

    def block_reason(self, user_id: str) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT state, expires_at FROM ai_access_rules WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None or (row["expires_at"] is not None and int(row["expires_at"]) <= self._now()):
            return None
        return str(row["state"])

    def access_status(self, user_id: str) -> dict[str, Any]:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT state, reason, expires_at FROM ai_access_rules WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or (row["expires_at"] is not None and int(row["expires_at"]) <= self._now()):
            return {"user_id": user_id, "state": "active", "reason": "", "expires_at": None}
        return {
            "user_id": user_id,
            "state": str(row["state"]),
            "reason": str(row["reason"]),
            "expires_at": None if row["expires_at"] is None else int(row["expires_at"]),
        }

    def stats(self) -> dict[str, int]:
        with self._database.connect() as connection:
            events = int(connection.execute("SELECT count(*) FROM events").fetchone()[0])
            memories = int(connection.execute("SELECT count(*) FROM memories WHERE status = 'active'").fetchone()[0])
            jobs = int(connection.execute("SELECT count(*) FROM memory_jobs WHERE status != 'completed'").fetchone()[0])
        return {"events": events, "active_memories": memories, "pending_jobs": jobs}

    def dashboard_snapshot(self, *, hours: int = 24) -> dict[str, Any]:
        if not 1 <= hours <= 720:
            raise ValueError("hours must be between 1 and 720")
        since = self._now() - hours * 3600
        with self._database.connect() as connection:
            requests = int(connection.execute("SELECT count(*) FROM events WHERE role = 'assistant' AND created_at >= ?", (since,)).fetchone()[0])
            users = int(connection.execute("SELECT count(DISTINCT user_id) FROM events WHERE created_at >= ?", (since,)).fetchone()[0])
            active_memories = int(connection.execute("SELECT count(*) FROM memories WHERE status = 'active'").fetchone()[0])
            pending_jobs = int(connection.execute("SELECT count(*) FROM memory_jobs WHERE status != 'completed'").fetchone()[0])
            summary_count = int(connection.execute("SELECT count(*) FROM conversation_summaries").fetchone()[0])
            rows = connection.execute("SELECT json_extract(metadata_json, '$.model') AS model, count(*) AS requests FROM events WHERE role = 'assistant' AND created_at >= ? GROUP BY model", (since,)).fetchall()
            token_estimate = int(connection.execute("SELECT coalesce(sum(input_tokens + output_tokens), 0) FROM ai_usage WHERE created_at >= ?", (since,)).fetchone()[0])
            provider_errors = int(connection.execute("SELECT count(*) FROM ai_provider_errors WHERE created_at >= ?", (since,)).fetchone()[0])
        by_model = {str(row["model"]): int(row["requests"]) for row in rows if row["model"]}
        return {"hours": hours, "requests_24h": requests, "active_users": users, "active_memories": active_memories, "pending_jobs": pending_jobs, "summaries": summary_count, "by_model": by_model, "token_estimate": token_estimate, "provider_errors": provider_errors}

    def list_memories(self, user_id: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        if not user_id.strip():
            raise ValueError("user id is required")
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT memory_id, scope_type, scope_id, memory_type, memory_key, status, importance, confidence, updated_at FROM memories WHERE user_id = ? ORDER BY updated_at DESC, memory_id LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def show_memory(self, user_id: str, memory_id: str) -> dict[str, Any]:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT memory_id, user_id, scope_type, scope_id, memory_type, memory_key, value_json, status, importance, confidence, created_at, updated_at FROM memories WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("memory not found for target user")
        return dict(row)

    def forget_memory(self, user_id: str, memory_id: str, *, actor_id: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE memories SET status = 'rejected', updated_at = ? WHERE memory_id = ? AND user_id = ? AND status != 'rejected'",
                (self._now(), memory_id, user_id),
            )
            if cursor.rowcount:
                self._audit(connection, actor_id, "memory.forget", memory_id, self._now())
            return bool(cursor.rowcount)

    def memory_evidence(self, user_id: str, memory_id: str) -> tuple[dict[str, Any], ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT e.event_id, e.role, e.created_at, substr(e.content, 1, 500) AS excerpt, me.relation FROM memory_evidence me JOIN memories m ON m.memory_id = me.memory_id JOIN events e ON e.event_id = me.event_id WHERE me.memory_id = ? AND m.user_id = ? ORDER BY me.created_at, e.event_id",
                (memory_id, user_id),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def export_history(self, user_id: str, *, limit: int = 500) -> str:
        if not user_id.strip():
            raise ValueError("user id is required")
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT event_id, channel_id, conversation_id, role, content, created_at FROM events WHERE user_id = ? ORDER BY created_at, event_id LIMIT ?",
                (user_id, limit),
            ).fetchall()
        lines = [f"# AI History Export: {user_id}", ""]
        for row in rows:
            lines.extend((f"## {row['event_id']} ({row['role']}, {row['created_at']})", f"- Channel: `{row['channel_id']}`", f"- Conversation: `{row['conversation_id']}`", "", str(row["content"]), ""))
        return "\n".join(lines)

    def export_memories(self, user_id: str, *, limit: int = 500) -> str:
        """Render the owner's complete, user-scoped memory snapshot as Markdown."""

        if not user_id.strip():
            raise ValueError("user id is required")
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT m.memory_id, m.scope_type, m.scope_id, m.memory_type, m.memory_key, m.value_json, m.status, m.importance, m.confidence, m.created_at, m.updated_at, count(me.event_id) AS evidence_count "
                "FROM memories m LEFT JOIN memory_evidence me ON me.memory_id = m.memory_id "
                "WHERE m.user_id = ? GROUP BY m.memory_id ORDER BY m.updated_at DESC, m.memory_id LIMIT ?",
                (user_id, limit),
            ).fetchall()
        lines = [f"# AI Memory Export: {user_id}", ""]
        for row in rows:
            try:
                value = json.loads(str(row["value_json"]))
            except json.JSONDecodeError:
                value = str(row["value_json"])
            rendered_value = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            safe_value = rendered_value.replace("`", "\\`")
            lines.extend((
                f"## {row['memory_id']}",
                f"- Key: `{row['memory_type']}.{row['memory_key']}`",
                f"- Scope: `{row['scope_type']}` / `{row['scope_id']}`",
                f"- Status: {row['status']}",
                f"- Importance: {row['importance']} | Confidence: {row['confidence']}",
                f"- Evidence records: {row['evidence_count']}",
                f"- Value: `{safe_value}`",
                "",
            ))
        return "\n".join(lines)

    def diagnose(self, area: str = "database") -> dict[str, Any]:
        if area != "database":
            raise ValueError("unknown diagnostic area")
        with self._database.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = int(connection.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0])
            migration = int(connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0])
        return {"schema_version": max(version, migration), "table_count": tables}

    def audit(self, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT actor_id, action, target_id, created_at FROM ai_operation_audit ORDER BY audit_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def _set_rule(self, user_id: str, state: str, actor_id: str, *, reason: str = "", expires_at: int | None = None) -> None:
        if not user_id.strip() or not actor_id.strip():
            raise ValueError("user and actor ids are required")
        normalized_reason = reason.strip()[:500]
        now = self._now()
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO ai_access_rules (user_id, state, reason, actor_id, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, reason = excluded.reason, actor_id = excluded.actor_id, expires_at = excluded.expires_at, updated_at = excluded.updated_at",
                (user_id, state, normalized_reason, actor_id, expires_at, now, now),
            )
            self._audit(connection, actor_id, "access.ban" if state == "banned" else "access.restrict", user_id, now)

    def _remove_rule(self, user_id: str, state: str, actor_id: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute("DELETE FROM ai_access_rules WHERE user_id = ? AND state = ?", (user_id, state))
            if cursor.rowcount:
                self._audit(connection, actor_id, f"access.{state}.remove", user_id, self._now())
            return bool(cursor.rowcount)

    @staticmethod
    def _audit(connection: Any, actor_id: str, action: str, target_id: str, created_at: int) -> None:
        connection.execute("INSERT INTO ai_operation_audit (actor_id, action, target_id, created_at) VALUES (?, ?, ?, ?)", (actor_id, action, target_id, created_at))

    @staticmethod
    def _ensure_user_state(connection: Any, user_id: str, now: int) -> None:
        connection.execute("INSERT INTO ai_user_state (user_id, updated_at) VALUES (?, ?) ON CONFLICT(user_id) DO NOTHING", (user_id, now))
