"""
tests/test_release_builder.py

Modification():

- 驗證發布清單排除 Secret、Runtime data 與部署端 Settings。
- 驗證必要文件與啟動檔仍會被封裝。

本檔不建立真實 Discord 連線。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

from tools.build_release import PROJECT_ROOT, build_release, release_files, should_include


def test_release_filter_excludes_private_runtime_content() -> None:
    assert not should_include(PROJECT_ROOT.joinpath(".env").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("data/database/ai.db").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("settings/ai.json").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath(".venv/lib/example.py").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("bot/__pycache__/x.pyc").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath(".env.production").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath(".superpowers/sdd/task.md").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("docs/superpowers/plans/internal.md").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("bridge/minecraft-bridge/logs/latest.log.gz").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("tools/build_release.py").relative_to(PROJECT_ROOT))


def test_release_filter_keeps_public_project_files() -> None:
    names = {path.relative_to(PROJECT_ROOT).as_posix() for path in release_files()}
    assert "main.py" in names
    assert ".env.example" in names
    assert "settings/README.md" in names
    assert "docs/RELEASE.md" in names
    assert "requirements.txt" in names
    assert "requirements-lock.txt" in names
    assert "tests/test_release_builder.py" not in names
    assert "bridge/minecraft-bridge/build.gradle" not in names


def test_release_files_reject_symlinks_and_unknown_top_level_files(tmp_path: Path) -> None:
    (tmp_path / "bot").mkdir()
    (tmp_path / "bot" / "app.py").write_text("print('ok')", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-private.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "bot" / "linked.py").symlink_to(outside)
    (tmp_path / "private-notes.txt").write_text("do not publish", encoding="utf-8")

    names = {path.relative_to(tmp_path).as_posix() for path in release_files(tmp_path)}

    assert names == {"bot/app.py"}


def test_release_zip_is_reproducible_valid_and_contains_required_files(tmp_path: Path) -> None:
    first = build_release(tmp_path / "first.zip")
    second = build_release(tmp_path / "second.zip")

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
    prefix = "Discord-Bot-v" + (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f"{prefix}/main.py" in names
    assert f"{prefix}/README.md" in names
    assert all("/.env" not in name or name.endswith("/.env.example") for name in names)
    assert all("/data/" not in name for name in names)


def test_ci_uploads_verified_runtime_and_bridge_artifacts() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "needs: [test, bridge]" in workflow
    assert workflow.count("uses: actions/upload-artifact@v4") == 2
    assert "dist/Discord-Bot-v${{ steps.version.outputs.value }}.zip" in workflow
    assert "path: bridge/java_bridge.jar" in workflow
