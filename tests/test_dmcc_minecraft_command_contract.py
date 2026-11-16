"""tests/test_dmcc_minecraft_command_contract.py

Modification():
- Verify Fabric and NeoForge expose the safe local DMCC command surface.
- Guard post-reload rejection of packets from a retired authenticated peer.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fabric_and_neoforge_register_native_commands() -> None:
    for path in (
        ROOT / "bridge/minecraft-bridge/src/main/java/io/miki/dmcc/bridge/BridgeMod.java",
        ROOT / "bridge/neoforge-bridge/src/main/java/io/miki/dmcc/bridge/NeoBridgeMod.java",
    ):
        source = path.read_text(encoding="utf-8")
        for command in ("link", "unlink", "help", "info", "stats", "update", "reload"):
            assert f'literal("{command}")' in source, (path, command)
        assert "reloadLocalConfiguration" in source
        assert "hasPermission(4)" in source
        assert "isCurrentConnection(client)" in source


def test_socket_generation_fences_stale_packets() -> None:
    runtime = (
        ROOT / "bridge/minecraft-bridge/src/main/java/io/miki/dmcc/bridge/BridgeRuntime.java"
    ).read_text(encoding="utf-8")
    for fragment in ("configurationGeneration", "reconfigure(", "isCurrentConnection(",
                     "sendForGeneration(", "failPending(requiredOutbound"):
        assert fragment in runtime


def test_new_native_queries_are_bounded() -> None:
    sources = ROOT / "bridge/minecraft-bridge/src/main/java/io/miki/dmcc/bridge"
    stats = (sources / "BridgeLocalStats.java").read_text(encoding="utf-8")
    updates = (sources / "BridgeUpdateChecker.java").read_text(encoding="utf-8")
    assert ".limit(2048)" in stats
    assert "Math.min(10, rows.size())" in stats
    assert "16_385" in updates
    assert "HttpClient.Redirect.NEVER" in updates
