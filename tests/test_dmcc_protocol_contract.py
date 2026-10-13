"""
tests/test_dmcc_protocol_contract.py
Modification(): 驗證 Java/Python DMCC server-info 診斷欄位共用契約。
"""

from __future__ import annotations

import json
from pathlib import Path

from bot.mod.dmcc.commands.user import render_server_info


def test_server_info_contract_is_rendered_without_missing_values() -> None:
    contract = json.loads(
        Path("bridge/protocol/server_info_response.json").read_text(encoding="utf-8")
    )
    response = {
        "online_players": 1,
        "max_players": 20,
        "player_names": ["Miki"],
        "minecraft_version": "1.21.8",
        "motd": "Test",
        **{key: "" if expected == "string" else 0 for key, expected in contract.items()},
    }

    rendered = render_server_info("survival", response)

    assert "required 0/0, events 0/0" in rendered
    assert "Dropped events: 0" in rendered
    assert "Last sender failure: none" in rendered
    assert "unavailable" not in rendered


def test_server_info_missing_diagnostics_are_not_reported_as_healthy() -> None:
    rendered = render_server_info("survival", {})

    assert "required unavailable/unavailable" in rendered
    assert "Last sender failure: unavailable" in rendered
