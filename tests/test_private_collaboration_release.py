"""
tests/test_private_collaboration_release.py

Modification():
- Keep internal AI collaboration journals, planning notes, and governance drafts
  out of both Git staging defaults and distributable runtime ZIP archives.
"""

from __future__ import annotations

from pathlib import Path

from tools.build_release import PROJECT_ROOT, should_include


def test_private_collaboration_paths_are_ignored_and_not_released() -> None:
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    forbidden = (
        "data/superpowers/plan.md",
        ".superpowers/notes.md",
        "docs/superpowers/plan.md",
        "docs/internal/collaboration.md",
        "docs/worklogs/session.md",
        "docs/collaboration/review-draft.md",
        ".worktrees/agent-session/notes.md",
    )
    for path in forbidden:
        assert not should_include(Path(path)), f"Runtime ZIP would expose {path}"
    for pattern in ("data/", ".superpowers/", "docs/superpowers/", "docs/internal/", "docs/worklogs/", "docs/collaboration/", ".worktrees/"):
        assert pattern in ignored, f".gitignore missing private category: {pattern}"
