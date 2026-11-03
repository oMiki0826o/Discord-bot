"""
tests/test_ai_agent_telemetry.py

Modification():
- Verify operational traces contain only fixed event kinds without secret text.
"""
from __future__ import annotations

import pytest

from bot.mod.ai.database import AiDatabase
from bot.mod.ai.operations import AiOperations


def test_agent_lifecycle_kind_persisted_for_trace_lookup(tmp_path) -> None:
    db = AiDatabase(tmp_path / "ai.db")
    db.initialize()
    operations = AiOperations(db)
    operations.record_runtime_event("request-1", "user-1", "tool.complete")
    entries = operations.provider_trace("request-1")
    assert len(entries) == 1
    assert entries[0]["model"] == "agent-runtime"
    assert entries[0]["outcome"] == "tool.complete"


@pytest.mark.parametrize("kind", ["", "full prompt", "private:123", "model\nsecret"])
def test_agent_lifecycle_rejects_freeform_or_private_text(tmp_path, kind) -> None:
    db = AiDatabase(tmp_path / "ai.db")
    db.initialize()
    operations = AiOperations(db)
    with pytest.raises(ValueError):
        operations.record_runtime_event("request-1", "user-1", kind)
