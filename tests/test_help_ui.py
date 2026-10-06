"""
tests/test_help_ui.py

Modification():

- 驗證 Help 分頁切割與中文分類名稱。
- 驗證 Help View 保存原始操作使用者。

本檔檢查 Help 介面的基本呈現資料。
"""

from __future__ import annotations

import pytest

discord = pytest.importorskip("discord")

from bot.core.discord.help.builder import build_help_categories
from bot.core.discord.help.models import HelpEntry
from bot.core.discord.help.view import HelpView


def test_help_pages_split_and_bind_owner() -> None:
    categories = build_help_categories(
        {"basic": [HelpEntry(name=f"command-{index}", description="測試") for index in range(7)]},
        category_name_resolver=lambda name: "基本功能" if name == "basic" else name,
    )
    assert len(categories) == 1
    assert categories[0].name == "基本功能"
    assert len(categories[0].pages) == 2
    view = HelpView(categories, user_id=123)
    assert view.user_id == 123
    assert len(view.category_select.options) == 1
