"""tests/test_release_integrity.py

Modification():

- Verifies the published Minecraft bridge artifact and deployment documents.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bridge_artifact_checksum_and_deployment_docs_exist() -> None:
    artifact = ROOT / "bridge" / "java_bridge.jar"
    checksums = ROOT / "bridge" / "SHA256SUMS"
    assert artifact.is_file()
    expected = checksums.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected
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
