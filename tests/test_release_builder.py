"""
tests/test_release_builder.py

Modification():

- 驗證發布清單排除 Secret、Runtime data 與部署端 Settings。
- 驗證必要文件與啟動檔仍會被封裝。

本檔不建立真實 Discord 連線。
"""

from __future__ import annotations

from tools.build_release import PROJECT_ROOT, release_files, should_include


def test_release_filter_excludes_private_runtime_content() -> None:
    assert not should_include(PROJECT_ROOT.joinpath(".env").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("data/database/ai.db").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("settings/ai.json").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath(".venv/lib/example.py").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("bot/__pycache__/x.pyc").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath(".env.production").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath(".superpowers/sdd/task.md").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("docs/superpowers/plans/internal.md").relative_to(PROJECT_ROOT))
    assert not should_include(PROJECT_ROOT.joinpath("tools/build_release.py").relative_to(PROJECT_ROOT))


def test_release_filter_keeps_public_project_files() -> None:
    names = {path.relative_to(PROJECT_ROOT).as_posix() for path in release_files()}
    assert "main.py" in names
    assert ".env.example" in names
    assert "settings/README.md" in names
    assert "docs/RELEASE.md" in names
    assert "requirements.txt" in names
    assert "requirements-dev.txt" in names
