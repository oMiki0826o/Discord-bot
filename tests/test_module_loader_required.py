"""
tests/test_module_loader_required.py

Modification():

- 驗證必要 Module 必須存在且不可被停用。
- 驗證執行期間停用或直接卸載必要 Module 會被拒絕。

本檔只測試 Module Loader 的必要模組契約，不連線 Discord。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.core.modules.loader import ModuleLoader
from bot.core.settings.manager import SettingsManager


class _Bot:
    def __init__(self) -> None:
        self.extensions: dict[str, object] = {}



def _loader(tmp_path) -> ModuleLoader:
    settings = SettingsManager(tmp_path / "settings", backup_dir=tmp_path / "backups")
    loader = ModuleLoader(
        bot=_Bot(),
        modules_dir=tmp_path / "modules",
        settings_manager=settings,
    )
    loader.registry.register("basic", "bot.mod.basic.extension")
    loader.registry.register("system", "bot.mod.system.extension")
    return loader


def test_required_modules_cannot_be_disabled(tmp_path) -> None:
    loader = _loader(tmp_path)
    loader.settings.set("modules.disabled", ["basic"])

    with pytest.raises(RuntimeError, match="必要 Module 不可停用：basic"):
        loader._validate_required_modules()


def test_required_modules_must_exist(tmp_path) -> None:
    loader = _loader(tmp_path)
    loader.registry.clear()
    loader.registry.register("basic", "bot.mod.basic.extension")

    with pytest.raises(RuntimeError, match="找不到必要 Module：system"):
        loader._validate_required_modules()


def test_disable_rejects_required_module(tmp_path) -> None:
    loader = _loader(tmp_path)

    assert asyncio.run(loader.disable("basic")) is False
    assert loader.settings.get("modules.disabled", []) == []


def test_unload_rejects_required_module(tmp_path) -> None:
    loader = _loader(tmp_path)

    assert asyncio.run(loader.unload("basic")) is False


def test_unload_all_can_release_required_modules(tmp_path) -> None:
    loader = _loader(tmp_path)
    loader.bot.extensions = {
        "bot.mod.basic.extension": object(),
        "bot.mod.system.extension": object(),
    }
    unloaded: list[str] = []

    async def _unload_extension(extension: str) -> None:
        unloaded.append(extension)
        loader.bot.extensions.pop(extension, None)

    loader.bot.unload_extension = _unload_extension

    assert asyncio.run(loader.unload_all()) is True
    assert set(unloaded) == {
        "bot.mod.basic.extension",
        "bot.mod.system.extension",
    }
