package io.miki.dmcc.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.advancements.AdvancementHolder;
import net.minecraft.advancements.AdvancementProgress;
import net.minecraft.advancements.DisplayInfo;
import net.minecraft.world.level.GameRules;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.storage.LevelResource;
import net.minecraft.commands.CommandSourceStack;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import static net.minecraft.commands.Commands.literal;

/**
 * Fabric server entrypoint for the staged DMCC Bridge.
 *
 * <p>The network client is deliberately added after the protocol handshake and Bridge configuration
 * layers have tests. Keeping this entrypoint small means the first generated JAR can safely load
 * without opening a connection to a Bot.</p>
 */
public final class BridgeMod implements ModInitializer {
    /** Stable logger name for server operators. */
    public static final Logger LOGGER = LoggerFactory.getLogger("minecraft_bridge");
    private static volatile BridgeMod activeInstance;
    private BridgeRuntime runtime;
    private String serverId;
    private final Map<String, PendingPlayer> pendingLinkPlayers = new ConcurrentHashMap<>();
    private final Map<String, PendingPlayer> pendingUnlinkPlayers = new ConcurrentHashMap<>();
    private volatile long pendingRequestTtlMillis = 120_000;
    private final ScheduledExecutorService statsWorker = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "dmcc-bridge-stats");
        thread.setDaemon(true);
        return thread;
    });

    @Override
    public void onInitialize() {
        activeInstance = this;
        ServerLifecycleEvents.SERVER_STARTED.register(this::startRuntime);
        ServerLifecycleEvents.SERVER_STOPPING.register(server -> stopRuntime());
        ServerMessageEvents.CHAT_MESSAGE.register((message, sender, params) ->
            relayPlayerChat(sender, message.signedContent())
        );
        ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> relayPlayerEvent("player_join", handler.getPlayer()));
        ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> handlePlayerDisconnect(handler.getPlayer()));
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
            literal("dmcc")
                .then(literal("link").executes(context -> requestLink(context.getSource().getEntity())))
                .then(literal("unlink").executes(context -> requestUnlink(context.getSource().getEntity())))
        ));
        LOGGER.info("Minecraft Bridge initialized; waiting for server lifecycle.");
    }

    /** Called only by the game-mode Mixin; no Discord API enters the Java process. */
    public static void relayGameModeChange(ServerPlayer player, GameType gameType) {
        BridgeMod active = activeInstance;
        if (active != null) active.sendGameModeChange(player, gameType);
    }

    /** Called only by the advancement Mixin after Minecraft has granted its reward. */
    public static void relayAdvancement(
        ServerPlayer player,
        AdvancementHolder advancement,
        AdvancementProgress progress
    ) {
        BridgeMod active = activeInstance;
        if (active != null) active.sendAdvancement(player, advancement, progress);
    }

    /** Called only by the player-death Mixin while the original death message remains available. */
    public static void relayDeath(ServerPlayer player) {
        BridgeMod active = activeInstance;
        if (active != null) active.sendDeath(player);
    }

    private void startRuntime(MinecraftServer server) {
        Path configPath = FabricLoader.getInstance().getConfigDir().resolve("minecraft-bridge.properties");
        try (var reader = Files.newBufferedReader(configPath)) {
            BridgeSettings settings = BridgeSettings.fromReader(reader);
            serverId = settings.serverId();
            pendingRequestTtlMillis = settings.pendingRequestTtlMillis();
            runtime = new BridgeRuntime(
                () -> new BridgeClient(settings, (client, envelope) -> handleGatewayPacket(server, client, envelope)),
                1_000,
                30_000,
                () -> sendServerStarted(server)
            );
            runtime.start();
            statsWorker.scheduleAtFixedRate(this::cleanupExpiredPending, 60, 60, TimeUnit.SECONDS);
            LOGGER.info("Minecraft Bridge connecting as server_id={}", settings.serverId());
        } catch (IOException | ProtocolException exception) {
            LOGGER.error("Minecraft Bridge disabled: unable to read {}", configPath, exception);
        }
    }

    private void handleGatewayPacket(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        if (envelope.type().equals("command_request")) {
            handleCommandRequest(server, client, envelope);
            return;
        }
        if (envelope.type().equals("link_response")) {
            handleLinkResponse(server, envelope);
            return;
        }
        if (envelope.type().equals("unlink_response")) {
            handleUnlinkResponse(server, envelope);
            return;
        }
        if (envelope.type().equals("server_info_request")) {
            handleServerInfoRequest(server, client, envelope);
            return;
        }
        if (envelope.type().equals("autocomplete_request")) {
            handleAutocompleteRequest(server, client, envelope);
            return;
        }
        if (envelope.type().equals("log_request")) {
            handleLogRequest(server, client, envelope);
            return;
        }
        if (envelope.type().equals("stats_request")) {
            handleStatsRequest(server, client, envelope);
            return;
        }
        if (!envelope.type().equals("minecraft_message")) return;
        Object rawMessage = envelope.data().get("message");
        if (!(rawMessage instanceof String message) || message.isBlank()) return;
        server.execute(() -> server.getPlayerList().broadcastSystemMessage(Component.literal(message), false));
    }

    private void relayPlayerChat(ServerPlayer player, String content) {
        if (content.isBlank() || runtime == null || serverId == null) return;
        if (!runtime.publishEvent(new ProtocolEnvelope(1, "player_chat", serverId, null,
                Map.of("minecraft_uuid", player.getStringUUID(), "player_name", player.getName().getString(), "message", content)))) {
            LOGGER.debug("DMCC player chat skipped because the Bridge is offline");
        }
    }

    private void relayPlayerEvent(String type, ServerPlayer player) {
        if (runtime == null || serverId == null) return;
        if (!runtime.publishEvent(new ProtocolEnvelope(1, type, serverId, null,
                Map.of("minecraft_uuid", player.getStringUUID(), "player_name", player.getName().getString())))) {
            LOGGER.debug("DMCC {} skipped because the Bridge is offline", type);
        }
    }

    private void sendGameModeChange(ServerPlayer player, GameType gameType) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null) return;
        if (!active.publishEvent(new ProtocolEnvelope(1, "player_gamemode", serverId, null, Map.of(
                "minecraft_uuid", player.getStringUUID(),
                "player_name", player.getName().getString(),
                "game_mode", gameType.getLongDisplayName().getString()
            )))) {
            LOGGER.debug("DMCC game mode event skipped because the Bridge is offline");
        }
    }

    private void sendDeath(ServerPlayer player) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null) return;
        if (!active.publishEvent(new ProtocolEnvelope(1, "player_death", serverId, null, Map.of(
                "minecraft_uuid", player.getStringUUID(),
                "player_name", player.getName().getString(),
                "death_message", player.getCombatTracker().getDeathMessage().getString()
            )))) {
            LOGGER.debug("DMCC death event skipped because the Bridge is offline");
        }
    }

    private void sendAdvancement(
        ServerPlayer player,
        AdvancementHolder advancement,
        AdvancementProgress progress
    ) {
        DisplayInfo display = advancement.value().display().orElse(null);
        if (display == null || !display.shouldAnnounceChat() || !progress.isDone()
            || !player.level().getGameRules().getBoolean(GameRules.RULE_ANNOUNCE_ADVANCEMENTS)) return;
        String type = switch (display.getType()) {
            case TASK -> "task";
            case GOAL -> "goal";
            case CHALLENGE -> "challenge";
        };
        BridgeRuntime active = runtime;
        if (active == null || serverId == null) return;
        if (!active.publishEvent(new ProtocolEnvelope(1, "player_advancement", serverId, null, Map.of(
                "minecraft_uuid", player.getStringUUID(),
                "player_name", player.getName().getString(),
                "title", display.getTitle().getString(),
                "description", display.getDescription().getString(),
                "advancement_type", type
            )))) {
            LOGGER.debug("DMCC advancement event skipped because the Bridge is offline");
        }
    }


    private int requestLink(net.minecraft.world.entity.Entity entity) {
        if (!(entity instanceof ServerPlayer player)) {
            return 0;
        }
        BridgeRuntime active = runtime;
        if (active == null) {
            player.sendSystemMessage(Component.literal("DMCC Bridge is not connected."));
            return 0;
        }
        String requestId = UUID.randomUUID().toString();
        cleanupExpiredPending();
        pendingLinkPlayers.put(requestId, new PendingPlayer(player.getUUID(), pendingDeadline()));
        active.sendRequired(new ProtocolEnvelope(1, "link_request", serverId, requestId,
            Map.of("minecraft_uuid", player.getStringUUID(), "minecraft_name", player.getName().getString())))
            .whenComplete((ignored, failure) -> {
                if (failure != null) pendingLinkPlayers.remove(requestId);
            });
        player.sendSystemMessage(Component.literal("DMCC: requesting a link code..."));
        return 1;
    }

    private void handleLinkResponse(MinecraftServer server, ProtocolEnvelope envelope) {
        if (envelope.requestId() == null) return;
        PendingPlayer pending = pendingLinkPlayers.remove(envelope.requestId());
        Object rawCode = envelope.data().get("code");
        if (pending == null || pending.expired() || !(rawCode instanceof String code) || code.isBlank()) return;
        server.execute(() -> {
            ServerPlayer player = server.getPlayerList().getPlayer(pending.playerId());
            if (player != null) {
                player.sendSystemMessage(Component.literal("DMCC link code: " + code + " — use /dmcc link " + code + " in Discord."));
            }
        });
    }

    private int requestUnlink(net.minecraft.world.entity.Entity entity) {
        if (!(entity instanceof ServerPlayer player)) return 0;
        BridgeRuntime active = runtime;
        if (active == null) {
            player.sendSystemMessage(Component.literal("DMCC Bridge is not connected."));
            return 0;
        }
        String requestId = UUID.randomUUID().toString();
        cleanupExpiredPending();
        pendingUnlinkPlayers.put(requestId, new PendingPlayer(player.getUUID(), pendingDeadline()));
        active.sendRequired(new ProtocolEnvelope(1, "unlink_request", serverId, requestId,
            Map.of("minecraft_uuid", player.getStringUUID())))
            .whenComplete((ignored, failure) -> {
                if (failure != null) pendingUnlinkPlayers.remove(requestId);
            });
        return 1;
    }

    private void handleUnlinkResponse(MinecraftServer server, ProtocolEnvelope envelope) {
        if (envelope.requestId() == null) return;
        PendingPlayer pending = pendingUnlinkPlayers.remove(envelope.requestId());
        Object rawRemoved = envelope.data().get("removed");
        if (pending == null || pending.expired() || !(rawRemoved instanceof Boolean removed)) return;
        server.execute(() -> {
            ServerPlayer player = server.getPlayerList().getPlayer(pending.playerId());
            if (player != null) {
                player.sendSystemMessage(Component.literal(removed ? "DMCC account unlinked." : "No DMCC account link found."));
            }
        });
    }

    private void handleCommandRequest(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        Object rawCommand = envelope.data().get("command");
        if (!(rawCommand instanceof String command) || command.isBlank() || envelope.requestId() == null) return;
        int opLevel = boundedOpLevel(envelope.data().get("op_level"));
        server.execute(() -> {
            DmccRconConsoleSource source = new DmccRconConsoleSource(server);
            int result;
            try {
                String normalized = command.startsWith("/") ? command.substring(1) : command;
                result = server.getCommands().getDispatcher().execute(
                    normalized,
                    buildCommandSource(server, source, opLevel)
                );
            } catch (CommandSyntaxException exception) {
                result = 0;
                source.sendSystemMessage(Component.literal(exception.getMessage()));
            }
            sendRequired(new ProtocolEnvelope(1, "command_response", envelope.serverId(), envelope.requestId(),
                Map.of("output", source.getCommandResponse(), "result", result)), "command response");
        });
    }

    private static int boundedOpLevel(Object rawLevel) {
        if (!(rawLevel instanceof Number number)) return 0;
        return Math.max(0, Math.min(4, number.intValue()));
    }

    private long pendingDeadline() {
        return System.currentTimeMillis() + pendingRequestTtlMillis;
    }

    private void cleanupExpiredPending() {
        pendingLinkPlayers.values().removeIf(PendingPlayer::expired);
        pendingUnlinkPlayers.values().removeIf(PendingPlayer::expired);
    }

    private record PendingPlayer(UUID playerId, long expiresAtMillis) {
        boolean expired() {
            return expiresAtMillis <= System.currentTimeMillis();
        }
    }

    private static CommandSourceStack buildCommandSource(
        MinecraftServer server,
        DmccRconConsoleSource source,
        int opLevel
    ) {
        return server.createCommandSourceStack()
            .withSource(source)
            .withPermission(opLevel)
            .withSuppressedOutput();
    }

    private void handleServerInfoRequest(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        if (envelope.requestId() == null) return;
        server.execute(() -> {
            sendRequired(new ProtocolEnvelope(1, "server_info_response", envelope.serverId(), envelope.requestId(), Map.of(
                    "online_players", server.getPlayerCount(),
                    "max_players", server.getMaxPlayers(),
                    "player_names", server.getPlayerList().getPlayers().stream().map(player -> player.getName().getString()).toList(),
                    "minecraft_version", server.getServerVersion(),
                    "motd", server.getMotd()
                )), "server info response");
        });
    }

    private void handleAutocompleteRequest(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        Object rawInput = envelope.data().get("input");
        if (!(rawInput instanceof String input) || envelope.requestId() == null) return;
        int opLevel = boundedOpLevel(envelope.data().get("op_level"));
        server.execute(() -> {
            var commandSource = buildCommandSource(server, new DmccRconConsoleSource(server), opLevel);
            var parsed = server.getCommands().getDispatcher().parse(input, commandSource);
            server.getCommands().getDispatcher().getCompletionSuggestions(parsed).thenAccept(suggestions -> {
                sendRequired(new ProtocolEnvelope(1, "autocomplete_response", envelope.serverId(), envelope.requestId(),
                    Map.of("suggestions", suggestions.getList().stream().map(suggestion -> suggestion.getText()).toList())),
                    "autocomplete response");
            });
        });
    }

    private void handleLogRequest(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        if (envelope.requestId() == null || !"latest.log".equals(envelope.data().get("name"))) return;
        Path logPath = server.getServerDirectory().resolve("logs").resolve("latest.log").normalize();
        try {
            String content = Files.exists(logPath) ? Files.readString(logPath) : "";
            if (content.length() > 32_768) content = content.substring(content.length() - 32_768);
            sendRequired(new ProtocolEnvelope(1, "log_response", envelope.serverId(), envelope.requestId(), Map.of("content", content)), "log response");
        } catch (IOException exception) {
            sendRequired(new ProtocolEnvelope(1, "log_response", envelope.serverId(), envelope.requestId(),
                Map.of("error", "latest.log is unavailable")), "log error response");
        }
    }

    /**
     * Implements the upstream stats command at the Minecraft boundary.  Python receives
     * only a compact leaderboard and never receives a path or reads a world file itself.
     */
    private void handleStatsRequest(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        if (envelope.requestId() == null) return;
        Object rawType = envelope.data().get("stat_type");
        Object rawStat = envelope.data().get("stat");
        if (!(rawType instanceof String requestedType) || !(rawStat instanceof String requestedStat)
            || requestedType.isBlank() || requestedStat.isBlank()) return;
        String statType = normalizeMinecraftIdentifier(requestedType);
        String stat = normalizeMinecraftIdentifier(requestedStat);
        server.execute(() -> {
            Path statsDirectory = server.getWorldPath(LevelResource.PLAYER_STATS_DIR);
            Map<UUID, String> onlineNames = server.getPlayerList().getPlayers().stream().collect(
                java.util.stream.Collectors.toUnmodifiableMap(ServerPlayer::getUUID, player -> player.getName().getString())
            );
            statsWorker.execute(() -> readAndSendStats(
                client, envelope, statType, stat, statsDirectory, onlineNames
            ));
        });
    }

    private void readAndSendStats(
        BridgeClient client,
        ProtocolEnvelope envelope,
        String statType,
        String stat,
        Path statsDirectory,
        Map<UUID, String> onlineNames
    ) {
        List<Map<String, Object>> entries = new ArrayList<>();
        try {
                if (Files.isDirectory(statsDirectory)) {
                    try (Stream<Path> stream = Files.list(statsDirectory)) {
                        for (Path path : stream.filter(Files::isRegularFile)
                            .filter(item -> item.getFileName().toString().endsWith(".json")).toList()) {
                            String fileName = path.getFileName().toString();
                            String uuidText = fileName.substring(0, fileName.length() - ".json".length());
                            try {
                                UUID uuid = UUID.fromString(uuidText);
                                int value = readStatValue(path, statType, stat);
                                if (value > 0) {
                                    String name = onlineNames.getOrDefault(uuid, uuidText);
                                    entries.add(Map.of("player_name", name, "value", value));
                                }
                            } catch (IllegalArgumentException ignored) {
                                // Ignore malformed or non-player statistics files as upstream does.
                            }
                        }
                    }
                }
                sendRequired(new ProtocolEnvelope(1, "stats_response", envelope.serverId(), envelope.requestId(), Map.of(
                    "stat_type", statType,
                    "stat", stat,
                    "entries", entries
                )), "stats response");
        } catch (IOException exception) {
                sendRequired(new ProtocolEnvelope(1, "stats_response", envelope.serverId(), envelope.requestId(), Map.of(
                        "stat_type", statType,
                        "stat", stat,
                        "entries", List.of(),
                        "error", "minecraft statistics are unavailable"
                    )), "stats error response");
        }
    }

    private static String normalizeMinecraftIdentifier(String value) {
        return value.contains(":") ? value : "minecraft:" + value;
    }

    private static int readStatValue(Path statsPath, String statType, String stat) throws IOException {
        JsonElement root = JsonParser.parseString(Files.readString(statsPath));
        if (!root.isJsonObject()) return 0;
        JsonObject statistics = root.getAsJsonObject().getAsJsonObject("stats");
        if (statistics == null) return 0;
        JsonObject typeEntries = statistics.getAsJsonObject(statType);
        if (typeEntries == null) return 0;
        JsonElement value = typeEntries.get(stat);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber()
            ? value.getAsInt() : 0;
    }

    private void stopRuntime() {
        if (runtime != null) {
            sendServerStopping();
            runtime.close();
            runtime = null;
        }
        pendingLinkPlayers.clear();
        pendingUnlinkPlayers.clear();
        statsWorker.shutdownNow();
    }

    private void sendServerStarted(MinecraftServer server) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null) return;
        active.sendRequired(new ProtocolEnvelope(1, "server_started", serverId, null, Map.of(
                "motd", server.getMotd(),
                "minecraft_version", server.getServerVersion()
            ))).whenComplete((ignored, failure) -> {
                if (failure != null) LOGGER.debug("DMCC server_started skipped because the Bridge is offline", failure);
            });
    }

    private void sendServerStopping() {
        if (serverId == null) return;
        runtime.publishEvent(new ProtocolEnvelope(1, "server_stopping", serverId, null, Map.of()));
    }

    private void sendRequired(ProtocolEnvelope envelope, String description) {
        BridgeRuntime active = runtime;
        if (active == null) return;
        active.sendRequired(envelope).whenComplete((ignored, failure) -> {
            if (failure != null) LOGGER.warn("Unable to return DMCC {}", description, failure);
        });
    }

    private void handlePlayerDisconnect(ServerPlayer player) {
        UUID playerId = player.getUUID();
        pendingLinkPlayers.values().removeIf(item -> item.playerId().equals(playerId));
        pendingUnlinkPlayers.values().removeIf(item -> item.playerId().equals(playerId));
        relayPlayerEvent("player_quit", player);
    }
}
