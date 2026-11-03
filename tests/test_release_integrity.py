"""tests/test_release_integrity.py

Modification():

- Verifies the published Minecraft bridge artifact and deployment documents.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bridge_artifact_is_built_in_ci_from_matching_sources() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "./gradlew --no-daemon test remapJar" in workflow
    assert "cp build/libs/minecraft-bridge-0.2.4.jar ../java_bridge.jar" in workflow
    assert "sha256sum java_bridge.jar > SHA256SUMS" in workflow
    assert "uses: actions/download-artifact@v4" in workflow
    assert "bridge/java_bridge.jar" in workflow
    assert (ROOT / "docs" / "DMCC.md").is_file()
    assert (ROOT / "docs" / "MC_BACKUP.md").is_file()


def test_bridge_release_includes_reproducible_gradle_sources() -> None:
    source = ROOT / "bridge" / "minecraft-bridge"
    assert (source / "gradlew").is_file()
    assert (source / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file()
    assert (source / "build.gradle").is_file()
    assert (source / "settings.gradle").is_file()
    assert (source / "src" / "main" / "java" / "io" / "miki" / "dmcc" / "bridge" / "BridgeMod.java").is_file()
    assert (source / "src" / "test" / "java" / "io" / "miki" / "dmcc" / "bridge" / "BridgeRuntimeTest.java").is_file()
