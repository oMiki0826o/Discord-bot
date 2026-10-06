"""
tests/test_mcwiki_importer.py

Modification():

- 提供 test mcwiki importer 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from tools.import_mcwiki import namespace_ids, render_markdown, safe_filename, selected_namespaces


def test_mcwiki_importer_creates_stable_safe_markdown_with_attribution() -> None:
    assert safe_filename("命令/execute:測試", 42) == "命令_execute_測試__42.md"

    document = render_markdown(
        title="命令", page_id=42, revision_id=99, fetched_at="2026-10-01T00:00:00Z",
        source_url="https://zh.minecraft.wiki/w/命令?oldid=99", text="第一段\n\n第二段",
    )

    assert "title: 命令" in document
    assert "revision_id: 99" in document
    assert "CC BY-NC-SA 3.0" in document
    assert "# 命令" in document
    assert "第一段" in document


def test_namespace_ids_accepts_mediawiki_mapping_response() -> None:
    payload = {"0": {"id": 0}, "6": {"id": 6}, "-1": {"id": -1}}

    assert namespace_ids(payload) == [0, 6]


def test_selected_namespaces_defaults_to_articles_only() -> None:
    class Arguments:
        namespace = None
        all_namespaces = False

    class Client:
        def namespaces(self) -> list[int]:
            return [0, 1, 6]

    assert selected_namespaces(Arguments(), Client()) == [0]


def test_selected_namespaces_allows_explicit_all_namespaces() -> None:
    class Arguments:
        namespace = None
        all_namespaces = True

    class Client:
        def namespaces(self) -> list[int]:
            return [0, 1, 6]

    assert selected_namespaces(Arguments(), Client()) == [0, 1, 6]
