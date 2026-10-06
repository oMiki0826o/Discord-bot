"""bot/mod/mc_backup/extension.py

Composition root and reversible lifecycle for standalone mc_backup.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from pathlib import Path

from .application.backup import BackupCoordinator
from .application.operations import OperationLockPool
from .application.schedules import BackupScheduleService
from .commands.owner import McBackupOwnerCog
from .config import DEFAULT_SETTINGS, SETTINGS_NAME, McBackupSettings, build_settings_schema
from .providers.local_tar import LocalTarBackupProvider
from .providers.local_tmux import LocalTmuxControlProvider
from .repositories.history import JsonHistoryRepository
from .repositories.schedules import JsonScheduleRepository

MODULE_VERSION = "0.1.0"
MODULE_DISPLAY_NAME = "Minecraft 備份與回檔"
MODULE_DEPENDENCIES: tuple[str, ...] = ()


@dataclass(slots=True)
class _Runtime:
    schedules: BackupScheduleService
    cog_name: str


_loaded: weakref.WeakKeyDictionary[object, _Runtime] = weakref.WeakKeyDictionary()


async def setup(bot, *, settings_registry=None, data_dir: Path | None = None) -> None:
    """Register settings and assemble only resources owned by mc_backup."""

    if bot in _loaded:
        raise RuntimeError("mc_backup module is already loaded")
    settings_registry, data_dir = _resolve_host_paths(settings_registry, data_dir)
    raw = _register_settings(settings_registry)
    settings = McBackupSettings.from_mapping(raw)
    history = JsonHistoryRepository(data_dir / "operations" / "history.json", max_records=int(raw["history_limit"]))
    control = LocalTmuxControlProvider(timeout_seconds=float(raw["control_timeout_seconds"]))
    archive = LocalTarBackupProvider()
    coordinator = BackupCoordinator(control, archive, history, OperationLockPool())
    schedules = BackupScheduleService({item.server_id: item for item in settings.servers}, coordinator, JsonScheduleRepository(data_dir / "schedules.json"))
    cog = McBackupOwnerCog(bot, settings=settings, coordinator=coordinator, schedules=schedules, confirmation_timeout_seconds=float(raw["confirmation_timeout_seconds"]))
    added = False
    try:
        await schedules.start()
        await bot.add_cog(cog)
        added = True
    except BaseException:
        if added and getattr(bot, "get_cog", lambda _name: None)(cog.qualified_name) is not None:
            await bot.remove_cog(cog.qualified_name)
        await schedules.close()
        raise
    _loaded[bot] = _Runtime(schedules, cog.qualified_name)


async def teardown(bot) -> None:
    """Cancel schedules and remove the owner Cog; safe for repeated calls."""

    runtime = _loaded.pop(bot, None)
    if runtime is None:
        return
    try:
        if getattr(bot, "get_cog", lambda _name: None)(runtime.cog_name) is not None:
            await bot.remove_cog(runtime.cog_name)
    finally:
        await runtime.schedules.close()


def _resolve_host_paths(settings_registry, data_dir: Path | None):
    if settings_registry is None:
        from bot.config import DATABASE_DIR
        from bot.core.settings.manager import settings

        settings_registry = settings
        data_dir = DATABASE_DIR.parent / "mc_backup"
    return settings_registry, data_dir or Path("data") / "mc_backup"


def _register_settings(settings_registry) -> dict[str, object]:
    try:
        from bot.core.settings.schema import SettingRule

        return settings_registry.register(SETTINGS_NAME, DEFAULT_SETTINGS, build_settings_schema(SettingRule))
    except ModuleNotFoundError:
        return settings_registry.register(SETTINGS_NAME, DEFAULT_SETTINGS)
