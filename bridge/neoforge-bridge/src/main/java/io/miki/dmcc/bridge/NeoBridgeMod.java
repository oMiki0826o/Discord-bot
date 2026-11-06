package io.miki.dmcc.bridge;

import com.mojang.brigadier.exceptions.CommandSyntaxException;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.ModList;
import net.neoforged.fml.common.Mod;
import net.neoforged.fml.loading.FMLPaths;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import net.neoforged.neoforge.event.ServerChatEvent;
import net.neoforged.neoforge.event.entity.player.PlayerEvent;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStoppingEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import static net.minecraft.commands.Commands.literal;

/**
 * NeoForge dedicated-server backend for the existing authenticated DMCC gateway.
 *
 * Uses precisely the same HMAC/length-framed transport as Fabric. All game
 * mutations are scheduled on the server thread. Does not silently claim that
 * Fabric-only mixins or login gating exist on NeoForge.
 */
@Mod(value = "minecraft_bridge", dist = Dist.DEDICATED_SERVER)
public final class NeoBridgeMod {
    private static final Logger LOGGER = LoggerFactory.getLogger("minecraft_bridge/neoforge");
    private final Map<String, UUID> pendingLinks = new ConcurrentHashMap<>();
    private final OpSyncApplier operators = new OpSyncApplier();
    private BridgeRuntime runtime;
    private BridgeSettings settings;
    private MinecraftServer minecraft;
    private int metricTicks;

    public NeoBridgeMod() {
        NeoForge.EVENT_BUS.register(this);
    }

    @SubscribeEvent
    public void onServerStarted(ServerStartedEvent event) {
        MinecraftServer server = event.getServer();
        Path config = FMLPaths.CONFIGDIR.get().resolve("minecraft-bridge.properties");
        try (var reader = Files.newBufferedReader(config)) {
            BridgeSettings loaded = BridgeSettings.fromReader(reader);
            if (loaded.requireLinking()) {
                throw new ProtocolException(
                    "NeoForge account login freeze/kick is not yet supported; disable require_linking"
                );
            }
            this.minecraft = server;
            this.settings = loaded;
            this.runtime = new BridgeRuntime(
                () -> new BridgeClient(loaded, (client, packet) -> handlePacket(server, packet)),
                1_000, 30_000, () -> sendStarted(server)
            );
            runtime.start();
            LOGGER.info("NeoForge Minecraft Bridge connecting as {}", loaded.serverId());
        } catch (IOException | ProtocolException error) {
            LOGGER.error("NeoForge Minecraft Bridge could not start: {}", config, error);
        }
    }

    @SubscribeEvent
    public void onServerStopping(ServerStoppingEvent event) {
        BridgeRuntime current = runtime;
        if (current == null || settings == null) return;
        current.closeGracefully(
            new ProtocolEnvelope(1, "server_stopping", settings.serverId(), null, Map.of()),
            Duration.ofMillis(settings.gracefulShutdownTimeoutMillis())
        );
        current.close();
        operators.clear();
        pendingLinks.clear();
        runtime = null;
        settings = null;
        minecraft = null;
    }

    @SubscribeEvent
    public void onServerChat(ServerChatEvent event) {
        ServerPlayer player = event.getPlayer();
        if (player != null && event.getRawText() != null && !event.getRawText().isBlank()) {
            publish("player_chat", Map.of(
                "minecraft_uuid", player.getStringUUID(),
                "player_name", player.getName().getString(),
                "message", event.getRawText()
            ));
        }
    }

    @SubscribeEvent
    public void onPlayerJoin(PlayerEvent.PlayerLoggedInEvent event) {
        if (event.getEntity() instanceof ServerPlayer player) {
            sendPlayerEvent("player_join", player);
        }
    }

    @SubscribeEvent
    public void onPlayerQuit(PlayerEvent.PlayerLoggedOutEvent event) {
        if (event.getEntity() instanceof ServerPlayer player) {
            pendingLinks.values().removeIf(uuid -> uuid.equals(player.getUUID()));
            sendPlayerEvent("player_quit", player);
        }
    }

    @SubscribeEvent
    public void onTick(ServerTickEvent.Post event) {
        BridgeRuntime current = runtime;
        MinecraftServer server = minecraft;
        if (current == null || server == null || settings == null || ++metricTicks < 300) return;
        metricTicks = 0;
        current.publishEvent(new ProtocolEnvelope(
            1, "server_metrics", settings.serverId(), null,
            MetricSnapshot.from(
                server.getAverageTickTimeNanos() / 1_000_000.0,
                server.getPlayerCount(), server.getMaxPlayers()
            )
        ));
    }

    @SubscribeEvent
    public void onCommands(RegisterCommandsEvent event) {
        event.getDispatcher().register(
            literal("dmcc")
                .then(literal("link").executes(ctx -> requestLink(ctx.getSource())))
                .then(literal("unlink").executes(ctx -> requestUnlink(ctx.getSource())))
        );
    }

    private int requestLink(CommandSourceStack source) throws CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        BridgeRuntime current = runtime;
        if (current == null || settings == null || !current.isAuthenticated()) {
            source.sendFailure(Component.literal("Discord Bridge is disconnected."));
            return 0;
        }
        String requestId = UUID.randomUUID().toString();
        pendingLinks.put(requestId, player.getUUID());
        current.sendRequired(new ProtocolEnvelope(1, "link_request", settings.serverId(), requestId,
            Map.of("minecraft_uuid", player.getStringUUID(),
                "minecraft_name", player.getName().getString())
        )).whenComplete((ignored, error) -> {
            if (error != null) pendingLinks.remove(requestId);
        });
        player.sendSystemMessage(Component.literal("DMCC: requesting a Discord link code."));
        return 1;
    }

    private int requestUnlink(CommandSourceStack source) throws CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        BridgeRuntime current = runtime;
        if (current == null || settings == null || !current.isAuthenticated()) {
            source.sendFailure(Component.literal("Discord Bridge is disconnected."));
            return 0;
        }
        String requestId = UUID.randomUUID().toString();
        pendingLinks.put(requestId, player.getUUID());
        current.sendRequired(new ProtocolEnvelope(1, "unlink_request", settings.serverId(), requestId,
            Map.of("minecraft_uuid", player.getStringUUID())
        )).whenComplete((ignored, error) -> {
            if (error != null) pendingLinks.remove(requestId);
        });
        return 1;
    }

    private void sendPlayerEvent(String event, ServerPlayer player) {
        publish(event, Map.of(
            "minecraft_uuid", player.getStringUUID(),
            "player_name", player.getName().getString()
        ));
    }

    private void publish(String kind, Map<String, Object> data) {
        BridgeRuntime current = runtime;
        BridgeSettings configured = settings;
        if (current != null && configured != null) {
            current.publishEvent(new ProtocolEnvelope(
                1, kind, configured.serverId(), null, data
            ));
        }
    }

    private void sendStarted(MinecraftServer server) {
        BridgeRuntime current = runtime;
        BridgeSettings configured = settings;
        if (current == null || configured == null) return;
        var mods = ModList.get().getMods().stream().limit(512).map(mod ->
            Map.of("mod_id", mod.getModId(), "version", mod.getVersion().toString())
        ).toList();
        current.sendRequired(new ProtocolEnvelope(
            1, "server_started", configured.serverId(), null, Map.of(
                "motd", server.getMotd(),
                "minecraft_version", server.getServerVersion(),
                "mods", mods
            )
        ));
    }

    private void handlePacket(MinecraftServer server, ProtocolEnvelope packet) {
        BridgeSettings configured = settings;
        BridgeRuntime current = runtime;
        if (configured == null || current == null || !packet.serverId().equals(configured.serverId())) return;
        if (packet.type().equals("link_response") || packet.type().equals("unlink_response")) {
            UUID playerId = pendingLinks.remove(packet.requestId());
            if (playerId == null) return;
            server.execute(() -> {
                ServerPlayer player = server.getPlayerList().getPlayer(playerId);
                if (player == null) return;
                if (packet.type().equals("link_response")) {
                    Object code = packet.data().get("code");
                    if (code instanceof String text && text.matches("[A-HJ-NP-Z2-9]{6}")) {
                        player.sendSystemMessage(Component.literal(
                            "DMCC link code: " + text + " — use /dmcc link " + text + " in Discord."
                        ));
                    }
                } else {
                    player.sendSystemMessage(Component.literal(
                        Boolean.TRUE.equals(packet.data().get("removed")) ?
                            "DMCC account unlinked." : "No DMCC account link found."
                    ));
                }
            });
            return;
        }
        if (packet.type().equals("minecraft_message")) {
            Object raw = packet.data().get("message");
            if (raw instanceof String message && !message.isBlank() && message.length() <= 2000) {
                server.execute(() -> server.getPlayerList().broadcastSystemMessage(
                    Component.literal(message), false
                ));
            }
            return;
        }
        if (packet.type().equals("minecraft_components")) {
            var content = RichTextComponents.parse(packet.data());
            content.ifPresent(component -> server.execute(() ->
                server.getPlayerList().broadcastSystemMessage(component, false)
            ));
            return;
        }
        if (packet.type().equals("player_mention")) {
            var mention = PlayerMentionRequest.parse(packet.data());
            mention.ifPresent(request -> server.execute(() -> {
                for (UUID uuid : request.players()) {
                    ServerPlayer player = server.getPlayerList().getPlayer(uuid);
                    if (player != null) {
                        player.displayClientMessage(Component.literal(request.message()), request.actionBar());
                    }
                }
            }));
            return;
        }
        if (packet.type().equals("op_sync_apply")) {
            if (!configured.opSyncEnabled()) return;
            var policy = OpSyncPolicy.parse(packet.data());
            policy.ifPresent(value -> server.execute(() -> operators.apply(server, value)));
            return;
        }
        if (packet.type().equals("server_info_request") && packet.requestId() != null) {
            server.execute(() -> {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("online_players", server.getPlayerCount());
                data.put("max_players", server.getMaxPlayers());
                data.put("player_names", server.getPlayerList().getPlayers().stream()
                    .map(player -> player.getName().getString()).toList());
                data.put("minecraft_version", server.getServerVersion());
                data.put("motd", server.getMotd());
                data.putAll(ServerInfoDiagnostics.from(current));
                respond(packet, "server_info_response", Map.copyOf(data));
            });
            return;
        }
        if (packet.type().equals("stats_request") && packet.requestId() != null) {
            server.execute(() -> respond(packet, "stats_response", MetricSnapshot.from(
                server.getAverageTickTimeNanos() / 1_000_000.0,
                server.getPlayerCount(), server.getMaxPlayers()
            )));
            return;
        }
        if (packet.type().equals("log_request") && packet.requestId() != null
            && "latest.log".equals(packet.data().get("name"))) {
            Thread worker = new Thread(() -> serveLog(server, packet), "dmcc-neoforge-log");
            worker.setDaemon(true);
            worker.start();
            return;
        }
        if (packet.type().equals("command_request") && packet.requestId() != null) {
            Object raw = packet.data().get("command");
            if (!(raw instanceof String command) || command.isBlank() || command.length() > 1024) return;
            Object permission = packet.data().get("op_level");
            int level = permission instanceof Number n ? Math.max(0, Math.min(4, n.intValue())) : 0;
            server.execute(() -> {
                DmccRconConsoleSource output = new DmccRconConsoleSource(server);
                int result = 0;
                try {
                    String normalized = command.startsWith("/") ? command.substring(1) : command;
                    result = server.getCommands().getDispatcher().execute(normalized,
                        server.createCommandSourceStack().withSource(output)
                            .withPermission(level).withSuppressedOutput());
                } catch (CommandSyntaxException error) {
                    output.sendSystemMessage(Component.literal(error.getMessage()));
                }
                respond(packet, "command_response", Map.of(
                    "output", output.getCommandResponse(), "result", result
                ));
            });
        }
    }

    private void serveLog(MinecraftServer server, ProtocolEnvelope packet) {
        Path path = server.getServerDirectory().resolve("logs/latest.log").normalize();
        try {
            if (packet.data().containsKey("offset")) {
                Object offset = packet.data().get("offset");
                Object fileId = packet.data().get("file_id");
                if (!(offset instanceof Number n) || !(fileId instanceof String id)
                    || n.doubleValue() != n.longValue()) return;
                var result = LogTailReader.readChunk(path, n.longValue(), id, 1024);
                respond(packet, "log_response", Map.of(
                    "content", result.content(), "file_id", result.fileId(),
                    "next_offset", result.nextOffset()
                ));
            } else {
                String contents = LogTailReader.read(path, 32_768);
                respond(packet, "log_response", Map.of("content", contents));
            }
        } catch (IOException | IllegalArgumentException problem) {
            respond(packet, "log_response", Map.of("content", "", "error", "log unavailable"));
        }
    }

    private void respond(ProtocolEnvelope request, String kind, Map<String, Object> data) {
        BridgeRuntime current = runtime;
        if (current != null && request.requestId() != null) {
            current.sendRequired(new ProtocolEnvelope(
                1, kind, request.serverId(), request.requestId(), data
            ));
        }
    }
}
