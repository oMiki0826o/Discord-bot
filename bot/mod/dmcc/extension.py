"""bot/mod/dmcc/extension.py
Composition root and reversible lifecycle for the standalone DMCC module.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import weakref
import os
from dataclasses import dataclass
from pathlib import Path

from .application.bridge_requests import BridgeRequestService
from .application.channel_mappings import ChannelMappingService
from .commands.owner import DmccOwnerCog
from .commands.user import DmccUserCog
from .config import DEFAULT_SETTINGS, SETTINGS_NAME, DmccSettings, build_settings_schema
from .gateway.server import Gateway
from .providers.control.local_tmux import LocalTmuxControlProvider
from .providers.control.mcsm import McsmControlProvider
from .providers.control.pterodactyl import PterodactylControlProvider
from .providers.panel_http import PanelHttpClient
from .repositories.links import JsonLinkRepository
from .repositories.state import JsonStateRepository
from .services.autocomplete import AutocompleteService
from .services.command_catalog import CommandCatalog, DmccMode
from .services.cross_server_relay import CrossServerRelayService
from .services.discord_relay import DiscordRelayService
from .services.info import InfoService
from .services.link_requests import LinkRequestHandler
from .services.linking import LinkingService
from .services.minecraft_discord_relay import MinecraftDiscordRelayService
from .services.op_levels import OpLevelResolver


MODULE_VERSION = "0.3.0"
MODULE_DISPLAY_NAME = "Discord Minecraft Chat"
MODULE_DEPENDENCIES: tuple[str, ...] = ()


@dataclass(slots=True)
class _Runtime:
    gateway: Gateway
    cog_names: tuple[str, ...]
    panel_clients: tuple[PanelHttpClient, ...]


_loaded_modules: weakref.WeakKeyDictionary[object, _Runtime] = weakref.WeakKeyDictionary()


def build_control_providers(settings: DmccSettings, environ=None):
    """Build only configured Panel controls and return their closeable clients."""

    environment = os.environ if environ is None else environ
    providers = {}
    clients: list[PanelHttpClient] = []
    for definition in settings.control_providers:
        options = definition.options
        if definition.provider_type == "local_tmux":
            providers[definition.provider_id] = LocalTmuxControlProvider(definition.provider_id, str(options["server_dir"]), str(options["session_name"]), tuple(str(item) for item in options["start_argv"]))
            continue
        key_name = str(options["api_key_env"])
        client = PanelHttpClient(str(options["base_url"]), str(environment[key_name]), auth_mode="query" if definition.provider_type == "mcsm" else "bearer")
        clients.append(client)
        if definition.provider_type == "pterodactyl":
            providers[definition.provider_id] = PterodactylControlProvider(
                definition.provider_id, client, str(options.get("server_identifier", definition.provider_id))
            )
        else:
            providers[definition.provider_id] = McsmControlProvider(
                definition.provider_id,
                client,
                str(options["daemon_id"]),
                str(options["instance_id"]),
            )
    return providers, tuple(clients)


async def setup(bot, *, settings_registry=None, state_path: Path | None = None) -> None:
    """Build all DMCC-owned resources and publish them only after startup succeeds."""

    if bot in _loaded_modules:
        raise RuntimeError("dmcc module is already loaded")
    settings_registry, state_path = _resolve_host_paths(settings_registry, state_path)
    raw_settings = _register_settings(settings_registry)
    settings = DmccSettings.from_mapping(raw_settings)
    state = JsonStateRepository(state_path)
    state.initialize()
    links = JsonLinkRepository(state_path.parent / "account_linking" / "links.json")
    gateway = Gateway(settings)
    _controls, panel_clients = build_control_providers(settings)
    added_cogs: list[str] = []
    try:
        await gateway.start()
        linking = LinkingService(link_store=links)
        gateway.relay.subscribe(LinkRequestHandler(linking, gateway).handle)
        if settings.cross_server_relay:
            gateway.relay.subscribe(
                CrossServerRelayService(
                    gateway,
                    lambda: tuple(
                        connection.server_id
                        for connection in gateway.manager.all()
                        if connection.server_id is not None
                    ),
                ).forward
            )
        if hasattr(bot, "add_cog"):
            user_cog, owner_cog = _build_cogs(
                bot,
                gateway,
                state,
                links,
                linking,
                raw_settings,
                settings,
            )
            gateway.relay.subscribe(MinecraftDiscordRelayService(state, user_cog).forward)
            for cog in (user_cog, owner_cog):
                await bot.add_cog(cog)
                added_cogs.append(cog.qualified_name)
    except BaseException:
        await _remove_cogs(bot, tuple(reversed(added_cogs)))
        await gateway.close()
        for client in panel_clients:
            await client.close()
        raise
    _loaded_modules[bot] = _Runtime(gateway, tuple(added_cogs), panel_clients)
    setattr(bot, "dmcc_gateway", gateway)


async def teardown(bot) -> None:
    """Remove all Discord and transport resources owned by this module."""

    runtime = _loaded_modules.pop(bot, None)
    if runtime is None:
        return
    try:
        await _remove_cogs(bot, tuple(reversed(runtime.cog_names)))
    finally:
        await runtime.gateway.close()
        for client in runtime.panel_clients:
            await client.close()
        if hasattr(bot, "dmcc_gateway"):
            delattr(bot, "dmcc_gateway")


def _build_cogs(
    bot,
    gateway: Gateway,
    state: JsonStateRepository,
    links: JsonLinkRepository,
    linking: LinkingService,
    raw_settings: dict[str, object],
    settings: DmccSettings,
) -> tuple[DmccUserCog, DmccOwnerCog]:
    catalog = CommandCatalog(DmccMode(settings.mode))
    info = InfoService(gateway, state, catalog)
    bridge = BridgeRequestService(gateway.requests)
    user = DmccUserCog(
        bot,
        relay=DiscordRelayService(state, gateway),
        linking=linking,
        info=info,
        catalog=catalog,
        op_levels=OpLevelResolver.from_mapping(raw_settings.get("permissions", {}), links),
        bridge=bridge,
        autocomplete=AutocompleteService(gateway.requests),
    )
    owner = DmccOwnerCog(
        bot,
        info=info,
        mappings=ChannelMappingService(state),
        bridge=bridge,
    )
    return user, owner


def _resolve_host_paths(settings_registry, state_path: Path | None):
    if settings_registry is None:
        from bot.config import DATABASE_DIR
        from bot.core.settings.manager import settings

        settings_registry = settings
        state_path = DATABASE_DIR.parent / "dmcc" / "state.json"
    return settings_registry, state_path or Path("data") / "dmcc" / "state.json"


def _register_settings(settings_registry) -> dict[str, object]:
    try:
        from bot.core.settings.schema import SettingRule

        return settings_registry.register(
            SETTINGS_NAME,
            DEFAULT_SETTINGS,
            build_settings_schema(SettingRule),
        )
    except (ModuleNotFoundError, TypeError):
        return settings_registry.register(SETTINGS_NAME, DEFAULT_SETTINGS)


async def _remove_cogs(bot, names: tuple[str, ...]) -> None:
    if not hasattr(bot, "remove_cog"):
        return
    for name in names:
        if not hasattr(bot, "get_cog") or bot.get_cog(name) is not None:
            await bot.remove_cog(name)
