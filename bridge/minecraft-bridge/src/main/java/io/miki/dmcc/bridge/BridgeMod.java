package io.miki.dmcc.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.google.gson.JsonParser;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.authlib.GameProfile;
import net.minecraft.network.Connection;
import net.minecraft.server.network.ServerLoginPacketListenerImpl;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundSetTitleTextPacket;
import net.minecraft.network.protocol.game.ClientboundSetTitlesAnimationPacket;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
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
import java.time.Duration;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.LinkedHashMap;
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
import static net.minecraft.commands.Commands.argument;

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
    private long metricTickCounter;
    private final Map<String, PendingPlayer> pendingLinkPlayers = new ConcurrentHashMap<>();
    private final CommandEchoSuppressor commandEchoes = new CommandEchoSuppressor();
    private final LinkGateRegistry loginGate = new LinkGateRegistry(
        System::nanoTime, TimeUnit.SECONDS.toNanos(5)
    );
    private volatile boolean requireLinking;
    private volatile String unlinkedPlayerAction = "kick";
    private volatile boolean opSyncEnabled;
    private volatile boolean relayPlayerCommands;
    private volatile boolean overwriteNativeMessages;
    private volatile MinecraftTranslations translations = MinecraftTranslations.empty();
    private volatile Path translationDirectory;
    private volatile String translationLocale = "en_us";
    private volatile String translationVersion;
    private volatile List<Path> translationRoots = List.of();
    private volatile MinecraftPackTranslations.Snapshot selectedPackTranslations =
        MinecraftPackTranslations.Snapshot.empty();
    private final OpSyncApplier opSyncApplier = new OpSyncApplier();
    private final FreezeRegistry frozenPlayers = new FreezeRegistry(
        System::nanoTime, TimeUnit.MINUTES.toNanos(5)
    );
    private final LinkGateRegistry freezeChecks = new LinkGateRegistry(
        System::nanoTime, TimeUnit.SECONDS.toNanos(5)
    );
    private final Map<UUID, FreezeSession> freezeSessions = new ConcurrentHashMap<>();
    private final Map<UUID, Long> freezeCorrectedAt = new ConcurrentHashMap<>();
    private final Map<String, PendingPlayer> pendingUnlinkPlayers = new ConcurrentHashMap<>();
    private volatile long pendingRequestTtlMillis = 120_000;
    private volatile int gracefulShutdownTimeoutMillis = 1_500;
    private final ScheduledExecutorService statsWorker = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "dmcc-bridge-stats");
        thread.setDaemon(true);
        return thread;
    });

    @Override
    public void onInitialize() {
        activeInstance = this;
        ServerLifecycleEvents.SERVER_STARTED.register(this::startRuntime);
        ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, manager, success) -> {
            if (success) {
                selectedPackTranslations = MinecraftPackTranslations.snapshot(
                    server, translationLocale
                );
                refreshTranslations();
            }
        });
        ServerLifecycleEvents.SERVER_STOPPING.register(server -> stopRuntime());
        ServerTickEvents.END_SERVER_TICK.register(server -> {
            checkFrozenPlayers(server);
            publishMetricsOnTick(server);
        });
        ServerMessageEvents.ALLOW_CHAT_MESSAGE.register((message, sender, params) -> {
            if (!overwriteNativeMessages) return true;
            if (sender.level().getServer() == null) return true;
            sender.level().getServer().getPlayerList().broadcastSystemMessage(
                NativeMessageFormatter.playerChat(sender.getName().getString(), message.signedContent()),
                false
            );
            relayPlayerChat(sender, message.signedContent());
            return false;
        });
        // Fabric API calls COMMAND_MESSAGE only for broadcasts addressed to
        // all players (e.g. /say and /me); recipient-scoped /msg is excluded.
        ServerMessageEvents.ALLOW_COMMAND_MESSAGE.register((message, source, params) -> {
            if (!overwriteNativeMessages) return true;
            source.getServer().getPlayerList().broadcastSystemMessage(
                NativeMessageFormatter.publicCommand(source.getTextName(), message.signedContent()),
                false
            );
            relayPublicCommand(source.getTextName(), message.signedContent());
            return false;
        });
        ServerMessageEvents.COMMAND_MESSAGE.register((message, source, params) ->
            relayPublicCommand(source.getTextName(), message.signedContent())
        );
        ServerMessageEvents.CHAT_MESSAGE.register((message, sender, params) ->
            relayPlayerChat(sender, message.signedContent())
        );
        ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {
            freezeOnJoin(handler.getPlayer());
            relayPlayerEvent("player_join", handler.getPlayer());
        });
        ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> handlePlayerDisconnect(handler.getPlayer()));
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
            literal("dmcc")
                .then(literal("link").executes(context -> requestLink(
                    context.getSource().getServer(), context.getSource().getEntity())))
                .then(literal("unlink").executes(context -> requestUnlink(
                    context.getSource().getServer(), context.getSource().getEntity())))
                .then(literal("refresh").requires(source -> source.hasPermission(3))
                    .executes(context -> refreshLocalPresentation(context.getSource().getServer())))
                .then(literal("pm")
                    .then(argument("player", StringArgumentType.word())
                        .then(argument("message", StringArgumentType.greedyString())
                            .executes(context -> sendPrivateFromMinecraft(
                                context.getSource(),
                                StringArgumentType.getString(context, "player"),
                                StringArgumentType.getString(context, "message")
                            )))))
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

    /** A strict public-command allowlist is checked before publishing any command. */
    public static void relayPlayerCommand(ServerPlayer player, String command) {
        BridgeMod mod = activeInstance;
        if (mod == null || !mod.relayPlayerCommands || player == null) return;
        String visible = PublicPlayerCommandPolicy.sanitize(command);
        if (visible.isEmpty() || mod.runtime == null || mod.serverId == null) return;
        mod.runtime.publishEvent(new ProtocolEnvelope(
            1, "player_command", mod.serverId, null,
            Map.of("minecraft_uuid", player.getStringUUID(),
                "player_name", player.getName().getString(), "message", visible)
        ));
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
            gracefulShutdownTimeoutMillis = settings.gracefulShutdownTimeoutMillis();
            requireLinking = settings.requireLinking();
            unlinkedPlayerAction = settings.unlinkedPlayerAction();
            opSyncEnabled = settings.opSyncEnabled();
            relayPlayerCommands = settings.relayPlayerCommands();
            overwriteNativeMessages = settings.overwriteNativeMessages();
            NativeMessageFormatter.configure(NativeFormatPolicy.load(configPath));
            translationLocale = settings.translationLocale();
            translationVersion = server.getServerVersion();
            translationDirectory = configPath.resolveSibling("minecraft-bridge").resolve("lang");
            translationRoots = FabricLoader.getInstance().getAllMods().stream()
                .flatMap(mod -> mod.getRootPaths().stream())
                .limit(256).toList();
            selectedPackTranslations = MinecraftPackTranslations.snapshot(server, translationLocale);
            refreshTranslations();
            statsWorker.scheduleAtFixedRate(this::refreshTranslations, 300, 300, TimeUnit.SECONDS);
            if (OfficialLanguageUpdater.enabled(configPath)) {
                OfficialLanguageUpdater updater = new OfficialLanguageUpdater();
                statsWorker.scheduleWithFixedDelay(() -> {
                    try {
                        if (updater.update(translationDirectory, translationVersion, translationLocale)) {
                            refreshTranslations();
                            LOGGER.info("DMCC official Minecraft language cache refreshed");
                        }
                    } catch (IOException invalid) {
                        LOGGER.warn("DMCC official language update skipped: {}", invalid.toString());
                    }
                }, 5, 43_200, TimeUnit.SECONDS);
            }
            if (opSyncEnabled) {
                try {
                    opSyncApplier.configure(configPath.resolveSibling("minecraft-bridge-managed-ops.properties"));
                } catch (IOException badLedger) {
                    opSyncEnabled = false;
                    LOGGER.error("DMCC OP sync disabled: ownership ledger unavailable", badLedger);
                }
            }
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

    /** Called from the login-thread mixin; never waits for Discord or another thread. */
    public static boolean shouldHoldLogin(
        ServerLoginPacketListenerImpl listener, Connection connection, GameProfile profile
    ) {
        BridgeMod mod = activeInstance;
        if (mod == null || !mod.requireLinking || !"kick".equals(mod.unlinkedPlayerAction)) return false;
        if (!connection.isConnected()) return false;
        UUID uuid = profileIdentifier(profile);
        String name = profileName(profile);
        if (uuid == null || name == null || !name.matches("[A-Za-z0-9_]{3,16}")) return false;
        BridgeRuntime active = mod.runtime;
        LinkGateRegistry.Decision decision = mod.loginGate.poll(
            uuid, connection, active != null && active.isAuthenticated(),
            requestId -> mod.sendLinkCheck(uuid, name, requestId)
        );
        if (decision.verdict() == LinkGateRegistry.Verdict.WAIT) return true;
        if (decision.verdict() == LinkGateRegistry.Verdict.DENY) {
            listener.disconnect(Component.literal(
                "Discord account linking required. In Discord use /dmcc link " + decision.code()
            ));
            return true;
        }
        return false;
    }

    private static UUID profileIdentifier(GameProfile profile) {
        Object value = profileAccessor(profile, "id", "getId");
        return value instanceof UUID uuid ? uuid : null;
    }

    private static String profileName(GameProfile profile) {
        Object value = profileAccessor(profile, "name", "getName");
        return value instanceof String name ? name : null;
    }

    private static Object profileAccessor(GameProfile profile, String first, String second) {
        for (String accessor : new String[]{first, second}) {
            try {
                return profile.getClass().getMethod(accessor).invoke(profile);
            } catch (ReflectiveOperationException | SecurityException ignored) {
                // Authlib has used both property and JavaBean names across MC versions.
            }
        }
        return null;
    }

    private boolean sendLinkCheck(UUID uuid, String name, String requestId) {
        BridgeRuntime active = runtime;
        if (active == null || !active.isAuthenticated() || serverId == null) return false;
        var sent = active.sendRequired(new ProtocolEnvelope(
            1, "link_status_request", serverId, requestId,
            Map.of("minecraft_uuid", uuid.toString(), "minecraft_name", name)
        ));
        return !sent.isCompletedExceptionally();
    }

    private void handleLinkStatusResponse(ProtocolEnvelope envelope) {
        Object uuid = envelope.data().get("minecraft_uuid");
        Object linked = envelope.data().get("linked");
        if (!(uuid instanceof String identifier) || !(linked instanceof Boolean result)
            || envelope.requestId() == null) return;
        try {
            UUID parsed = UUID.fromString(identifier);
            Object code = envelope.data().get("code");
            loginGate.respond(parsed, envelope.requestId(), result,
                code instanceof String text ? text : null);
            freezeChecks.respond(parsed, envelope.requestId(), result,
                code instanceof String text ? text : null);
        } catch (IllegalArgumentException ignored) {
            // Invalid or stale responses cannot prevent a vanilla login.
        }
    }

    /** Can be used by mixins on the server thread to gate frozen movement and actions. */
    public static boolean isFrozenPlayer(ServerPlayer player) {
        BridgeMod mod = activeInstance;
        if (mod == null || player == null) return false;
        BridgeRuntime active = mod.runtime;
        return mod.frozenPlayers.isFrozen(
            player.getUUID(), active != null && active.isAuthenticated()
        );
    }

    public static void correctFrozenPlayer(ServerPlayer player) {
        BridgeMod mod = activeInstance;
        if (mod == null || !isFrozenPlayer(player)) return;
        UUID uuid = player.getUUID();
        long now = System.nanoTime();
        Long last = mod.freezeCorrectedAt.get(uuid);
        if (last != null && now - last < TimeUnit.SECONDS.toNanos(1)) return;
        FreezeRegistry.Anchor anchor = mod.frozenPlayers.anchor(uuid);
        if (anchor == null) return;
        mod.freezeCorrectedAt.put(uuid, now);
        player.connection.teleport(anchor.x(), anchor.y(), anchor.z(), anchor.yaw(), anchor.pitch());
    }

    private void freezeOnJoin(ServerPlayer player) {
        BridgeRuntime active = runtime;
        if (!requireLinking || !"freeze".equals(unlinkedPlayerAction)
            || active == null || !active.isAuthenticated()) return;
        UUID uuid = player.getUUID();
        frozenPlayers.freeze(uuid, new FreezeRegistry.Anchor(
            player.getX(), player.getY(), player.getZ(), player.getYRot(), player.getXRot()
        ));
        freezeSessions.put(uuid, new FreezeSession());
        player.sendSystemMessage(Component.literal(
            "DMCC: Checking your Discord account link. You can still use chat and commands."
        ));
    }

    private void checkFrozenPlayers(MinecraftServer server) {
        if (freezeSessions.isEmpty()) return;
        BridgeRuntime active = runtime;
        boolean available = active != null && active.isAuthenticated();
        long now = System.nanoTime();
        for (var item : new ArrayList<>(freezeSessions.entrySet())) {
            UUID uuid = item.getKey();
            FreezeSession session = item.getValue();
            ServerPlayer player = server.getPlayerList().getPlayer(uuid);
            if (player == null || !frozenPlayers.isFrozen(uuid, available)) {
                releaseFreeze(uuid);
                continue;
            }
            if (now < session.nextRequestAtNanos) continue;
            LinkGateRegistry.Decision decision = freezeChecks.poll(
                uuid, player, available,
                requestId -> sendLinkCheck(uuid, player.getName().getString(), requestId)
            );
            if (decision.verdict() == LinkGateRegistry.Verdict.WAIT) continue;
            if (decision.verdict() == LinkGateRegistry.Verdict.ALLOW) {
                releaseFreeze(uuid);
                player.sendSystemMessage(Component.literal(
                    "DMCC: Account linking verified or service unavailable. You may play."
                ));
                continue;
            }
            String code = decision.code();
            if (!code.equals(session.lastCode)) {
                session.lastCode = code;
                player.sendSystemMessage(LinkPromptComponents.linkCode(code));
            }
            freezeChecks.clear(uuid);
            session.nextRequestAtNanos = now + TimeUnit.SECONDS.toNanos(15);
        }
    }

    private void releaseFreeze(UUID uuid) {
        frozenPlayers.release(uuid);
        freezeChecks.clear(uuid);
        freezeSessions.remove(uuid);
        freezeCorrectedAt.remove(uuid);
    }

    private static final class FreezeSession {
        long nextRequestAtNanos;
        String lastCode = "";
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
        if (envelope.type().equals("link_status_response")) {
            handleLinkStatusResponse(envelope);
            return;
        }
        if (envelope.type().equals("op_sync_apply")) {
            if (!opSyncEnabled) return;
            var validated = OpSyncPolicy.parse(envelope.data());
            if (validated.isEmpty()) return;
            server.execute(() -> {
                OpSyncApplier.ApplyReport result = opSyncApplier.applyWithReport(server, validated.get());
                if (result.updated() > 0) LOGGER.info(
                    "DMCC synchronized {} managed linked-player operator records", result.updated()
                );
                if (envelope.requestId() != null) {
                    sendRequired(new ProtocolEnvelope(
                        1, "op_sync_response", envelope.serverId(), envelope.requestId(),
                        Map.of("ok", result.failed() == 0,
                            "updated", result.updated(), "failed", result.failed())
                    ), "operator sync confirmation");
                }
            });
            return;
        }
        if (envelope.type().equals("minecraft_private_message")) {
            handlePrivateFromDiscord(server, envelope);
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
        if (envelope.type().equals("player_mention")) {
            var request = PlayerMentionRequest.parse(envelope.data());
            if (request.isEmpty()) return;
            server.execute(() -> {
                for (UUID uuid : request.get().players()) {
                    ServerPlayer target = server.getPlayerList().getPlayer(uuid);
                    if (target != null) {
                        PlayerMentionRequest mention = request.get();
                        Component notice = Component.literal(mention.message());
                        if (mention.style().equals("title")) {
                            target.connection.send(new ClientboundSetTitlesAnimationPacket(10, 70, 20));
                            target.connection.send(new ClientboundSetTitleTextPacket(notice));
                        } else {
                            target.displayClientMessage(notice, mention.actionBar());
                        }
                        if (mention.sound()) {
                            target.playNotifySound(SoundEvents.NOTE_BLOCK_PLING.value(), SoundSource.MASTER, 1.0F, 2.0F);
                        }
                    }
                }
            });
            return;
        }
        if (envelope.type().equals("minecraft_components")) {
            var decoded = RichTextComponents.parse(envelope.data());
            if (decoded.isEmpty()) return;
            server.execute(() -> server.getPlayerList().broadcastSystemMessage(decoded.get(), false));
            return;
        }
        if (!envelope.type().equals("minecraft_message")) return;
        Object rawMessage = envelope.data().get("message");
        if (!(rawMessage instanceof String message) || message.isBlank()) return;
        server.execute(() -> server.getPlayerList().broadcastSystemMessage(Component.literal(message), false));
    }

    /**
     * Reload local display, message and language settings without disconnecting
     * the authenticated transport or changing OP ownership.
     */
    private int refreshLocalPresentation(MinecraftServer server) {
        Path file = FabricLoader.getInstance().getConfigDir().resolve("minecraft-bridge.properties");
        try (var reader = Files.newBufferedReader(file)) {
            BridgeSettings snapshot = BridgeSettings.fromReader(reader);
            NativeFormatPolicy nativePolicy = NativeFormatPolicy.load(file);
            if (!snapshot.serverId().equals(serverId)) {
                LOGGER.warn("DMCC display refresh rejected: server_id changed");
                return 0;
            }
            NativeMessageFormatter.configure(nativePolicy);
            overwriteNativeMessages = snapshot.overwriteNativeMessages();
            relayPlayerCommands = snapshot.relayPlayerCommands();
            translationLocale = snapshot.translationLocale();
            selectedPackTranslations = MinecraftPackTranslations.snapshot(server, translationLocale);
            statsWorker.execute(this::refreshTranslations);
            LOGGER.info("DMCC presentation and language settings refreshed");
            return 1;
        } catch (IOException | ProtocolException invalid) {
            LOGGER.warn("DMCC presentation refresh rejected: {}", invalid.toString());
            return 0;
        }
    }

    private static String normalizePrivateText(Object raw) {
        if (!(raw instanceof String text) || text.isBlank() || text.length() > 750) return null;
        if (text.chars().anyMatch(ch -> ch < 32 || ch == 127)) return null;
        return text.strip().replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]");
    }

    /**
     * Minecraft's own /dmcc pm is explicit and recipient scoped. Never publish
     * this event to general Minecraft chat or the public Discord relay.
     */
    private int sendPrivateFromMinecraft(
        CommandSourceStack source, String targetName, String raw
    ) throws CommandSyntaxException {
        ServerPlayer sender = source.getPlayerOrException();
        if (targetName == null || !targetName.matches("[A-Za-z0-9_]{3,16}")) return 0;
        String message = normalizePrivateText(raw);
        if (message == null) return 0;
        ServerPlayer recipient = source.getServer().getPlayerList().getPlayerByName(targetName);
        if (recipient == null) {
            sender.sendSystemMessage(Component.literal("DMCC private: player is offline."));
            return 0;
        }
        recipient.sendSystemMessage(Component.literal(
            "[DMCC private] <" + sender.getName().getString() + "> " + message
        ));
        sender.sendSystemMessage(Component.literal(
            "[DMCC private → " + recipient.getName().getString() + "] " + message
        ));
        BridgeRuntime active = runtime;
        if (active != null && serverId != null) {
            active.publishEvent(new ProtocolEnvelope(
                1, "player_private_message", serverId, null, Map.of(
                    "sender_uuid", sender.getStringUUID(),
                    "sender_name", sender.getName().getString(),
                    "recipient_uuid", recipient.getStringUUID(),
                    "message", message
                )
            ));
        }
        return 1;
    }

    private void handlePrivateFromDiscord(MinecraftServer server, ProtocolEnvelope envelope) {
        Object rawUuid = envelope.data().get("recipient_uuid");
        Object rawSender = envelope.data().get("sender_name");
        String message = normalizePrivateText(envelope.data().get("message"));
        if (!(rawUuid instanceof String uuidText)
            || !uuidText.matches("[a-fA-F0-9-]{36}")
            || !(rawSender instanceof String senderName)
            || !senderName.matches("[A-Za-z0-9_]{3,16}")
            || message == null) {
            sendPrivateResult(envelope, false);
            return;
        }
        final UUID uuid;
        try {
            uuid = UUID.fromString(uuidText);
        } catch (IllegalArgumentException invalid) {
            sendPrivateResult(envelope, false);
            return;
        }
        server.execute(() -> {
            ServerPlayer recipient = server.getPlayerList().getPlayer(uuid);
            boolean delivered = recipient != null;
            if (delivered) {
                recipient.sendSystemMessage(Component.literal(
                    "[DMCC private Discord] <" + senderName + "> " + message
                ));
            }
            sendPrivateResult(envelope, delivered);
        });
    }

    private void sendPrivateResult(ProtocolEnvelope request, boolean ok) {
        if (request.requestId() == null) return;
        sendRequired(new ProtocolEnvelope(
            1, "minecraft_private_response", request.serverId(), request.requestId(),
            Map.of("ok", ok)
        ), "private message delivery status");
    }

    /** Sample cached game-server timing only once per 300 ticks, never perform network I/O here. */
    private void publishMetricsOnTick(MinecraftServer server) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null || ++metricTickCounter < 300) return;
        metricTickCounter = 0L;
        try {
            active.publishEvent(new ProtocolEnvelope(
                1, "server_metrics", serverId, null,
                MetricSnapshot.from(server.getAverageTickTimeNanos() / 1_000_000.0, server.getPlayerCount(), server.getMaxPlayers())
            ));
        } catch (IllegalArgumentException invalid) {
            LOGGER.debug("Unable to capture Minecraft server timing: {}", invalid.getMessage());
        }
    }

    /** Observe an explicitly public /tellraw command without changing vanilla delivery. */
    public static boolean isPublicTellrawCommand(String command) {
        return PublicTellrawPolicy.isPublicBroadcast(command);
    }

    public static void relayTellrawCommand(String sender, Component content) {
        BridgeMod mod = activeInstance;
        if (mod == null || content == null) return;
        String sanitized = PublicTellrawPolicy.sanitize(mod.translations.translate(content));
        if (!sanitized.isBlank()) mod.relayPublicCommand(sender, sanitized, "tell_raw");
    }

    private void relayPublicCommand(String sender, String content) {
        relayPublicCommand(sender, content, "broadcast");
    }

    private void relayPublicCommand(String sender, String content, String eventSource) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null || content == null || content.isBlank()) return;
        String safe = PublicTellrawPolicy.sanitize(content);
        if (safe.isBlank()) return;
        String senderName = sender == null || sender.isBlank() ? "Server" : sender;
        if (active.publishEvent(new ProtocolEnvelope(1, "server_broadcast", serverId, null, Map.of(
            "player_name", senderName,
            "message", safe,
            "source_event", eventSource
        )))) {
            commandEchoes.mark(senderName, content);
        }
    }

    private void relayPlayerChat(ServerPlayer player, String content) {
        if (content.isBlank() || runtime == null || serverId == null) return;
        if (commandEchoes.consume(player.getName().getString(), content)) return;
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

    /**
     * Immutable snapshots permit asynchronous reloads without exposing partial locale maps
     * to callbacks on the Minecraft tick thread.
     */
    private void refreshTranslations() {
        Path directory = translationDirectory;
        if (directory == null) return;
        try {
            translations = MinecraftTranslations.load(
                directory, translationLocale, translationRoots, translationVersion,
                selectedPackTranslations
            );
        } catch (IOException | IllegalArgumentException invalid) {
            LOGGER.warn("DMCC language catalogs unavailable; preserving previous snapshot: {}",
                invalid.toString());
        }
    }

    private void sendGameModeChange(ServerPlayer player, GameType gameType) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null) return;
        if (!active.publishEvent(new ProtocolEnvelope(1, "player_gamemode", serverId, null, Map.of(
                "minecraft_uuid", player.getStringUUID(),
                "player_name", player.getName().getString(),
                "game_mode", translations.translate(gameType.getLongDisplayName())
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
                "death_message", translations.translate(player.getCombatTracker().getDeathMessage())
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
                "title", translations.translate(display.getTitle()),
                "description", translations.translate(display.getDescription()),
                "advancement_type", type
            )))) {
            LOGGER.debug("DMCC advancement event skipped because the Bridge is offline");
        }
    }


    private int requestLink(MinecraftServer server, net.minecraft.world.entity.Entity entity) {
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
                if (failure != null && pendingLinkPlayers.remove(requestId) != null) {
                    notifyPlayerFailure(server, player.getUUID(), "DMCC link request could not be sent.");
                }
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
                player.sendSystemMessage(LinkPromptComponents.linkCode(code));
            }
        });
    }

    private int requestUnlink(MinecraftServer server, net.minecraft.world.entity.Entity entity) {
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
                if (failure != null && pendingUnlinkPlayers.remove(requestId) != null) {
                    notifyPlayerFailure(server, player.getUUID(), "DMCC unlink request could not be sent.");
                }
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
            BridgeRuntime active = runtime;
            if (active == null) return;
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("online_players", server.getPlayerCount());
            response.put("max_players", server.getMaxPlayers());
            response.put("player_names", server.getPlayerList().getPlayers().stream()
                .map(player -> player.getName().getString()).toList());
            response.put("minecraft_version", server.getServerVersion());
            response.put("motd", server.getMotd());
            response.putAll(ServerInfoDiagnostics.from(active));
            sendRequired(new ProtocolEnvelope(
                1, "server_info_response", envelope.serverId(), envelope.requestId(), Map.copyOf(response)
            ), "server info response");
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
        statsWorker.execute(() -> {
            try {
                if (envelope.data().containsKey("offset")) {
                    Object rawOffset = envelope.data().get("offset");
                    Object rawFileId = envelope.data().get("file_id");
                    if (!(rawOffset instanceof Number number) || !(rawFileId instanceof String fileId)
                        || fileId.length() > 64) return;
                    long offset = number.longValue();
                    if (offset < -1L || number.doubleValue() != (double) offset) return;
                    var chunk = LogTailReader.readChunk(logPath, offset, fileId, 1024);
                    sendRequired(new ProtocolEnvelope(1, "log_response", envelope.serverId(), envelope.requestId(),
                        Map.of("content", chunk.content(), "file_id", chunk.fileId(),
                            "next_offset", chunk.nextOffset())), "log cursor response");
                } else {
                    String content = LogTailReader.read(logPath, 131_072);
                    if (content.length() > 32_768) content = content.substring(content.length() - 32_768);
                    sendRequired(new ProtocolEnvelope(1, "log_response", envelope.serverId(), envelope.requestId(),
                        Map.of("content", content)), "log response");
                }
            } catch (IOException exception) {
                sendRequired(new ProtocolEnvelope(1, "log_response", envelope.serverId(), envelope.requestId(),
                    Map.of("error", "latest.log is unavailable")), "log error response");
            }
        });
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
                            } catch (IOException | JsonParseException | IllegalStateException
                                     | IllegalArgumentException exception) {
                                LOGGER.warn("Skipping malformed Minecraft statistics file {}: {}",
                                    path.getFileName(), exception.getClass().getSimpleName());
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
            ProtocolEnvelope stopping = new ProtocolEnvelope(
                1, "server_stopping", serverId, null, Map.of()
            );
            if (!runtime.closeGracefully(stopping, Duration.ofMillis(gracefulShutdownTimeoutMillis))) {
                LOGGER.warn("DMCC server_stopping was not delivered before shutdown");
            }
            runtime = null;
        }
        metricTickCounter = 0L;
        requireLinking = false;
        opSyncEnabled = false;
        relayPlayerCommands = false;
        overwriteNativeMessages = false;
        NativeMessageFormatter.configure(NativeFormatPolicy.defaults());
        opSyncApplier.clear();
        translations = MinecraftTranslations.empty();
        translationDirectory = null;
        translationVersion = null;
        translationRoots = List.of();
        selectedPackTranslations = MinecraftPackTranslations.Snapshot.empty();
        loginGate.clearAll();
        freezeChecks.clearAll();
        frozenPlayers.clearAll();
        freezeSessions.clear();
        freezeCorrectedAt.clear();
        pendingLinkPlayers.clear();
        pendingUnlinkPlayers.clear();
        statsWorker.shutdownNow();
    }

    private List<Map<String, String>> fabricModInventory() {
        return FabricLoader.getInstance().getAllMods().stream().limit(512).map(container -> Map.of(
            "mod_id", container.getMetadata().getId(),
            "version", container.getMetadata().getVersion().getFriendlyString()
        )).toList();
    }

    private void sendServerStarted(MinecraftServer server) {
        BridgeRuntime active = runtime;
        if (active == null || serverId == null) return;
        active.sendRequired(new ProtocolEnvelope(1, "server_started", serverId, null, Map.of(
                "motd", server.getMotd(),
                "minecraft_version", server.getServerVersion(),
                "mods", fabricModInventory()
            ))).whenComplete((ignored, failure) -> {
                if (failure != null) LOGGER.debug("DMCC server_started skipped because the Bridge is offline", failure);
            });
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
        releaseFreeze(playerId);
        pendingLinkPlayers.values().removeIf(item -> item.playerId().equals(playerId));
        pendingUnlinkPlayers.values().removeIf(item -> item.playerId().equals(playerId));
        relayPlayerEvent("player_quit", player);
    }

    private static void notifyPlayerFailure(MinecraftServer server, UUID playerId, String message) {
        server.execute(() -> {
            ServerPlayer player = server.getPlayerList().getPlayer(playerId);
            if (player != null) player.sendSystemMessage(Component.literal(message));
        });
    }
}
