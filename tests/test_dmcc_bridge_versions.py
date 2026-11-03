"""tests/test_dmcc_bridge_versions.py

Modification():

- Validate declared and continuously tested Minecraft-version build contracts.

"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fabric_metadata_is_pinned_per_build_version() -> None:
    mod = (ROOT / "bridge/minecraft-bridge/src/main/resources/fabric.mod.json").read_text()
    build = (ROOT / "bridge/minecraft-bridge/build.gradle").read_text()
    assert '"minecraft": "${minecraft_version}"' in mod
    assert 'inputs.property "minecraft_version"' in build
    assert '"minecraft_version": project.minecraft_version' in build


def test_ci_compiles_explicit_version_matrix() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "minecraft: '1.21.8'" in workflow
    assert "minecraft: '1.21.9'" in workflow
    assert "-Pminecraft_version=${{ matrix.minecraft }}" in workflow
    assert "minecraft-bridge-${{ matrix.minecraft }}" in workflow
    assert "uses: actions/download-artifact@v4" in workflow


def test_release_uses_only_ci_built_versioned_bridge_jars() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "bridge/versions/1.21.9" in workflow
    assert "bridge/builds/minecraft-bridge-1.21.8/java_bridge.jar" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow
