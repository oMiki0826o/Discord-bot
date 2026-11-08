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
from .application.power import PowerService
from .application.status import StatusQueryService
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
from .domain.registry import ServerRegistry
from .services.autocomplete import AutocompleteService
from .services.command_catalog import CommandCatalog, DmccMode
from .services.cross_server_relay import CrossServerRelayService
from .services.discord_delivery import DiscordDeliveryAdapter
from .services.event_queue import DiscordEventQueue
from .services.discord_relay import DiscordRelayService
from .services.info import InfoService
from .services.link_requests import LinkRequestHandler
from .services.linking import LinkingService
from .services.minecraft_discord_relay import MinecraftDiscordRelayService
from .services.monitoring import MonitoringService
from .services.mod_updates import ModUpdateService
from .services.console_stream import ConsoleStreamService
from .services.op_levels import OpLevelResolver
from .services.nickname_sync import NicknameSyncService
from .services.release_updates import ReleaseUpdateService
from .services.mentions import MinecraftMentionService
from .services.op_sync import OpSyncService
from .services.private_messages import DmPrivateMessageService, PrivateMessageConsent


MODULE_VERSION = "0.3.0"
MODULE_DISPLAY_NAME = "Discord Minecraft Chat"
MODULE_DEPENDENCIES: tuple[str, ...] = ()


@dataclass(slots=True)
class _Runtime:
    gateway: Gateway
    cog_names: tuple[str, ...]
    panel_clients: tuple[PanelHttpClient, ...]
    discord_queue: DiscordEventQueue | None = None
    monitor: MonitoringService | None = None
    updates: ModUpdateService | None = None
    console: ConsoleStreamService | None = None
    nicknames: NicknameSyncService | None = None
    release_updates: ReleaseUpdateService | None = None
    op_sync: OpSyncService | None = None


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
    controls, panel_clients = build_control_providers(settings)
    added_cogs: list[str] = []
    discord_queue: DiscordEventQueue | None = None
    monitor: MonitoringService | None = None
    updates: ModUpdateService | None = None
    console: ConsoleStreamService | None = None
    nicknames: NicknameSyncService | None = None
    release_updates: ReleaseUpdateService | None = None
    op_sync: OpSyncService | None = None
    preview_user_relay = None
    preview_inbound_relay = None
    preview_cross_server_relay = None
    private_relay = DmPrivateMessageService(
        bot, gateway, links,
        PrivateMessageConsent(state_path.parent / "private_consent.json"),
        settings.v3_features,
    )
    try:
        await gateway.start()
        linking = LinkingService(link_store=links, max_accounts=settings.max_linked_accounts)
        if settings.op_sync.enabled:
            op_sync = OpSyncService(
                settings.op_sync, bot, links,
                OpLevelResolver.from_mapping(raw_settings.get("permissions", {}), links),
                gateway.manager, gateway,
            )
            op_sync.start()
        gateway.relay.subscribe(LinkRequestHandler(linking, gateway).handle)
        gateway.relay.subscribe(private_relay.from_minecraft)
        if settings.nickname_sync.enabled:
            nicknames = NicknameSyncService(bot, links, settings.nickname_sync)
            nicknames.start()
        release_updates = ReleaseUpdateService(
            settings.release_check, DiscordDeliveryAdapter(bot), MODULE_VERSION
        )
        if settings.release_check.enabled:
            release_updates.start()
        if settings.cross_server_relay:
            preview_cross_server_relay = CrossServerRelayService(
                gateway,
                lambda: tuple(
                    connection.server_id
                    for connection in gateway.manager.all()
                    if connection.server_id is not None
                ),
                event_types=settings.cross_server_events,
                features=settings.v3_features,
            )
            gateway.relay.subscribe(preview_cross_server_relay.forward)
        if settings.monitoring.enabled:
            monitor = MonitoringService(bot, gateway.manager, settings.monitoring)
            gateway.relay.subscribe(monitor.on_event)
            monitor.start()
        if settings.mod_updates.enabled:
            updates = ModUpdateService(settings.mod_updates, DiscordDeliveryAdapter(bot), connection_manager=gateway.manager)
            gateway.relay.subscribe(updates.on_event)
            updates.start()
        if settings.console_stream.enabled:
            console = ConsoleStreamService(
                settings.console_stream,
                BridgeRequestService(gateway.requests),
                gateway.manager,
                DiscordDeliveryAdapter(bot),
                cursor_path=state_path.parent / "console_cursors.json",
            )
            console.start()
        if hasattr(bot, "add_cog"):
            user_cog, owner_cog = _build_cogs(
                bot,
                gateway,
                state,
                links,
                linking,
                raw_settings,
                settings,
                controls,
                nicknames,
                release_updates,
                private_relay,
            )
            preview_user_relay = user_cog._relay
            preview_inbound_relay = MinecraftDiscordRelayService(
                state, DiscordDeliveryAdapter(bot), settings.presentation,
                features=settings.v3_features,
            )
            discord_queue = DiscordEventQueue(preview_inbound_relay)
            discord_queue.start()
            gateway.relay.subscribe(discord_queue.publish)
            for cog in (user_cog, owner_cog):
                await bot.add_cog(cog)
                added_cogs.append(cog.qualified_name)
    except BaseException:
        if op_sync is not None:
            await op_sync.close()
        if release_updates is not None:
            await release_updates.close()
        if nicknames is not None:
            await nicknames.close()
        if console is not None:
            await console.close()
        if updates is not None:
            await updates.close()
        if monitor is not None:
            await monitor.close()
        if discord_queue is not None:
            await discord_queue.close()
        await _remove_cogs(bot, tuple(reversed(added_cogs)))
        await gateway.close()
        for client in panel_clients:
            await client.close()
        raise
    _loaded_modules[bot] = _Runtime(gateway, tuple(added_cogs), panel_clients, discord_queue, monitor, updates, console, nicknames, release_updates, op_sync)
    setattr(bot, "dmcc_gateway", gateway)

    async def refresh_preview_features() -> bool:
        # This operation only updates display/parser policy; sockets, credentials
        # and operator permissions keep their existing validated settings.
        load_settings = getattr(settings_registry, "load", None)
        if not callable(load_settings):
            return False
        try:
            fresh = DmccSettings.from_mapping(load_settings(SETTINGS_NAME))
        except (RuntimeError, ValueError, OSError):
            return False
        private_relay.refresh(fresh.v3_features)
        if preview_cross_server_relay is not None:
            preview_cross_server_relay.apply_preview_features(fresh.v3_features)
        if preview_user_relay is not None:
            preview_user_relay.apply_preview_features(fresh.v3_features)
        if preview_inbound_relay is not None:
            preview_inbound_relay.apply_preview_features(
                fresh.v3_features, fresh.presentation,
            )
        return True

    setattr(bot, "dmcc_refresh_preview", refresh_preview_features)


async def teardown(bot) -> None:
    """Remove all Discord and transport resources owned by this module."""

    runtime = _loaded_modules.pop(bot, None)
    if runtime is None:
        return
    try:
        await _remove_cogs(bot, tuple(reversed(runtime.cog_names)))
    finally:
        if runtime.op_sync is not None:
            await runtime.op_sync.close()
        if runtime.release_updates is not None:
            await runtime.release_updates.close()
        if runtime.nicknames is not None:
            await runtime.nicknames.close()
        if runtime.console is not None:
            await runtime.console.close()
        if runtime.updates is not None:
            await runtime.updates.close()
        if runtime.monitor is not None:
            await runtime.monitor.close()
        if runtime.discord_queue is not None:
            await runtime.discord_queue.close()
        await runtime.gateway.close()
        for client in runtime.panel_clients:
            await client.close()
        if hasattr(bot, "dmcc_gateway"):
            delattr(bot, "dmcc_gateway")
        if hasattr(bot, "dmcc_refresh_preview"):
            delattr(bot, "dmcc_refresh_preview")


def _build_cogs(
    bot,
    gateway: Gateway,
    state: JsonStateRepository,
    links: JsonLinkRepository,
    linking: LinkingService,
    raw_settings: dict[str, object],
    settings: DmccSettings,
    controls,
    nicknames: NicknameSyncService | None = None,
    release_updates: ReleaseUpdateService | None = None,
    private_relay: DmPrivateMessageService | None = None,
) -> tuple[DmccUserCog, DmccOwnerCog]:
    catalog = CommandCatalog(DmccMode(settings.mode))
    servers = ServerRegistry(settings.servers)
    info = InfoService(gateway, state, catalog)
    bridge = BridgeRequestService(gateway.requests)
    user = DmccUserCog(
        bot,
        relay=DiscordRelayService(
            state, gateway, rich_chat=settings.rich_chat,
            features=settings.v3_features,
        ),
        linking=linking,
        info=info,
        catalog=catalog,
        op_levels=OpLevelResolver.from_mapping(raw_settings.get("permissions", {}), links),
        bridge=bridge,
        autocomplete=AutocompleteService(gateway.requests),
        nicknames=nicknames,
        mentions=MinecraftMentionService(settings.mentions, state, links, gateway),
        release_updates=release_updates,
        private_messages=private_relay,
    )
    owner = DmccOwnerCog(
        bot,
        info=info,
        mappings=ChannelMappingService(state),
        bridge=bridge,
        status=StatusQueryService(servers, gateway.manager, controls),
        power=PowerService(servers, controls),
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
