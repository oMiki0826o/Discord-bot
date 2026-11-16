#!/usr/bin/env python3
"""Prepare the Fabric DMCC /dmcc reload change in a checked-out Discord-bot repo.

Usage:
  python3 apply_dmcc_reload.py /path/to/Discord-bot --check
  python3 apply_dmcc_reload.py /path/to/Discord-bot --apply

The script does not run git commands, push, merge, or touch live server config.
It checks source anchors before writing and prints unified diffs in check mode.
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import sys

SRC = Path('bridge/minecraft-bridge/src/main/java/io/miki/dmcc/bridge')
TEST = Path('bridge/minecraft-bridge/src/test/java/io/miki/dmcc/bridge')


def replace_once(text: str, before: str, after: str, filename: str) -> str:
    occurrences = text.count(before)
    if occurrences != 1:
        raise ValueError(f'{filename}: expected one source anchor, found {occurrences}: {before[:90]!r}')
    return text.replace(before, after, 1)


def patch_runtime(text: str) -> str:
    fn = 'BridgeRuntime.java'
    text = replace_once(text, 'import java.util.concurrent.atomic.AtomicLong;\n',
                        'import java.util.concurrent.atomic.AtomicLong;\nimport java.util.Objects;\nimport java.util.concurrent.locks.LockSupport;\n', fn)
    text = replace_once(text, 'private final Supplier<BridgeConnection> connectionFactory;',
                        'private volatile Supplier<BridgeConnection> connectionFactory;', fn)
    text = replace_once(text, '    private final AtomicLong droppedEvents = new AtomicLong();',
                        '    private final AtomicLong configurationGeneration = new AtomicLong();\n'
                        '    private volatile long activeGeneration;\n'
                        '    private volatile Thread connectionWorkerThread;\n'
                        '    private final AtomicLong droppedEvents = new AtomicLong();', fn)
    text = replace_once(text, 'Thread thread = new Thread(runnable, "dmcc-bridge");\n'
                        '        thread.setDaemon(true);\n        return thread;',
                        'Thread thread = new Thread(runnable, "dmcc-bridge");\n'
                        '        thread.setDaemon(true);\n        connectionWorkerThread = thread;\n'
                        '        return thread;', fn)
    needle = '    private void run() {\n        long delay = initialDelayMillis;\n        while (running) {\n            BridgeConnection candidate = null;'
    replacement = '''    /** Replace validated connection settings without replacing sender/worker threads.
     * Existing queued packets are tied to the previous peer and must not leak to
     * a newly authenticated server identity.
     */
    public void reconfigure(Supplier<BridgeConnection> nextFactory) {
        Objects.requireNonNull(nextFactory, "connection factory");
        if (!running || closed.get()) {
            throw new IllegalStateException("DMCC Bridge runtime is not running");
        }
        connectionFactory = nextFactory;
        configurationGeneration.incrementAndGet();
        failPending(requiredOutbound, new IOException("DMCC Bridge settings were reloaded"));
        eventOutbound.clear();
        BridgeConnection previous = connection;
        connection = null; // Reject responses from the previous peer immediately.
        if (previous != null) previous.close();
        Thread workerThread = connectionWorkerThread;
        if (workerThread != null) LockSupport.unpark(workerThread);
    }

    /** Reject callbacks arriving from an obsolete peer after a configuration change. */
    public boolean isCurrentConnection(BridgeConnection candidate) {
        return running && candidate != null && connection == candidate
            && activeGeneration == configurationGeneration.get();
    }

    private void run() {
        long delay = initialDelayMillis;
        while (running) {
            long attemptGeneration = configurationGeneration.get();
            BridgeConnection candidate = null;'''
    text = replace_once(text, needle, replacement, fn)
    text = replace_once(text,
                        '        BridgeConnection active = connection;\n        return running && active instanceof BridgeClient client',
                        '        BridgeConnection active = connection;\n'
                        '        return activeGeneration == configurationGeneration.get()\n'
                        '            && running && active instanceof BridgeClient client', fn)
    text = replace_once(text,
                        '        if (active == null) {\n            throw new IOException("DMCC Bridge is not connected");\n        }',
                        '        if (active == null || activeGeneration != configurationGeneration.get()) {\n'
                        '            throw new IOException("DMCC Bridge is not connected");\n        }', fn)
    text = replace_once(text,
                        '                candidate = connectionFactory.get();\n                connection = candidate;\n'
                        '                candidate.connect();\n                lastFailure = null;\n                connectedCallback.run();',
                        '                candidate = connectionFactory.get();\n                connection = candidate;\n'
                        '                activeGeneration = attemptGeneration;\n'
                        '                if (configurationGeneration.get() != attemptGeneration) continue;\n'
                        '                candidate.connect();\n'
                        '                if (configurationGeneration.get() != attemptGeneration) continue;\n'
                        '                lastFailure = null;\n                connectedCallback.run();', fn)
    needle = '''            try {
                Thread.sleep(delay);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            }
            delay = Math.min(maximumDelayMillis, Math.max(delay * 2, 1));'''
    replacement = '''            if (!running) return;
            if (configurationGeneration.get() != attemptGeneration) {
                delay = initialDelayMillis;
                continue;
            }
            // unpark() wakes this backoff when settings are reloaded; do not
            // interrupt the worker because that would terminate its run loop.
            LockSupport.parkNanos(TimeUnit.MILLISECONDS.toNanos(delay));
            if (!running) return;
            if (configurationGeneration.get() != attemptGeneration) {
                delay = initialDelayMillis;
                continue;
            }
            delay = Math.min(maximumDelayMillis, Math.max(delay * 2, 1));'''
    text = replace_once(text, needle, replacement, fn)
    # Tag pending packets with the peer generation. Clearing queues alone does
    # not protect packets already dequeued by the sender thread.
    text = replace_once(text, 'new Outbound(envelope, null)',
                        'new Outbound(envelope, null, configurationGeneration.get())', fn)
    text = replace_once(text, 'new Outbound(envelope, result)',
                        'new Outbound(envelope, result, configurationGeneration.get())', fn)
    text = replace_once(text,
        '    private record Outbound(ProtocolEnvelope envelope, CompletableFuture<Void> result) { }',
        '    private record Outbound(ProtocolEnvelope envelope, CompletableFuture<Void> result, long generation) { }', fn)
    text = replace_once(text,
        '    public void send(ProtocolEnvelope envelope) throws IOException {\n',
        '    public void send(ProtocolEnvelope envelope) throws IOException {\n'
        '        sendForGeneration(envelope, configurationGeneration.get());\n'
        '    }\n\n'
        '    private void sendForGeneration(ProtocolEnvelope envelope, long generation) throws IOException {\n'
        '        if (!running || generation != configurationGeneration.get()) {\n'
        '            throw new IOException("DMCC Bridge packet belongs to a retired connection");\n'
        '        }\n', fn)
    text = replace_once(text,
        '                send(item.envelope());\n',
        '                sendForGeneration(item.envelope(), item.generation());\n', fn)
    text = replace_once(text,
        '        if (active instanceof BridgeClient client && client.state() != BridgeClient.State.AUTHENTICATED) {\n'
        '            throw new IOException("DMCC Bridge is not authenticated");\n'
        '        }\n'
        '        active.send(envelope);',
        '        if (active instanceof BridgeClient client && client.state() != BridgeClient.State.AUTHENTICATED) {\n'
        '            throw new IOException("DMCC Bridge is not authenticated");\n'
        '        }\n'
        '        if (generation != configurationGeneration.get() || connection != active) {\n'
        '            throw new IOException("DMCC Bridge peer changed before packet delivery");\n'
        '        }\n'
        '        active.send(envelope);', fn)
    return text


def patch_mod(text: str) -> str:
    fn = 'BridgeMod.java'
    text = replace_once(text, '    private BridgeRuntime runtime;\n',
                        '    private volatile BridgeRuntime runtime;\n'
                        '    private volatile BridgeSettings appliedSettings;\n', fn)
    text = replace_once(text, '    private String serverId;\n',
                        '    private volatile String serverId;\n', fn)
    needle = '''                .then(literal("refresh").requires(source -> source.hasPermission(3))
                    .executes(context -> refreshLocalPresentation(context.getSource().getServer())))'''
    replacement = '''                .then(literal("refresh").requires(source -> source.hasPermission(3))
                    .executes(context -> refreshLocalPresentation(context.getSource().getServer())))
                .then(literal("reload").requires(source -> source.hasPermission(4))
                    .executes(context -> reloadLocalConfiguration(context.getSource())))'''
    text = replace_once(text, needle, replacement, fn)
    needle = '''            BridgeSettings settings = BridgeSettings.fromReader(reader);
            serverId = settings.serverId();'''
    replacement = '''            BridgeSettings settings = BridgeSettings.fromReader(reader);
            if (!"fabric".equals(settings.bridgeKind())) {
                throw new ProtocolException("Fabric bridge requires bridge_kind=fabric");
            }
            serverId = settings.serverId();'''
    text = replace_once(text, needle, replacement, fn)
    text = replace_once(text, '            runtime = new BridgeRuntime(',
                        '            appliedSettings = settings;\n            runtime = new BridgeRuntime(', fn)
    needle = '''    private void handleGatewayPacket(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        if (envelope.type().equals("command_request")) {'''
    replacement = '''    private void handleGatewayPacket(MinecraftServer server, BridgeClient client, ProtocolEnvelope envelope) {
        BridgeRuntime active = runtime;
        if (active == null || !active.isCurrentConnection(client)) return;
        if (envelope.type().equals("command_request")) {'''
    text = replace_once(text, needle, replacement, fn)
    # Avoid processing privileged packets that were accepted by an obsolete
    # connection but are still queued on Minecraft's main-thread executor.
    text = replace_once(text,
        '            server.execute(() -> {\n                OpSyncApplier.ApplyReport result =',
        '            server.execute(() -> {\n'
        '                BridgeRuntime live = runtime;\n'
        '                if (live == null || !live.isCurrentConnection(client)) return;\n'
        '                OpSyncApplier.ApplyReport result =', fn)
    text = replace_once(text,
        '        server.execute(() -> {\n            DmccRconConsoleSource source = new DmccRconConsoleSource(server);',
        '        server.execute(() -> {\n'
        '            BridgeRuntime live = runtime;\n'
        '            if (live == null || !live.isCurrentConnection(client)) return;\n'
        '            DmccRconConsoleSource source = new DmccRconConsoleSource(server);', fn)
    needle = '''    private int refreshLocalPresentation(MinecraftServer server) {'''
    new_method = '''    /** Reload the entire Fabric bridge config, keeping the live runtime on parse failure.
     * Network connections are rebuilt only if the peer/auth settings changed.
     * The command runs on the Minecraft thread, while reconnects remain on the
     * existing BridgeRuntime worker thread.
     */
    private int reloadLocalConfiguration(CommandSourceStack source) {
        MinecraftServer server = source.getServer();
        Path file = FabricLoader.getInstance().getConfigDir().resolve("minecraft-bridge.properties");
        try {
            final BridgeSettings next;
            try (var reader = Files.newBufferedReader(file)) {
                next = BridgeSettings.fromReader(reader);
            }
            if (!"fabric".equals(next.bridgeKind())) {
                throw new ProtocolException("Fabric bridge requires bridge_kind=fabric");
            }
            // Parse every local format option before changing the active runtime.
            NativeFormatPolicy format = NativeFormatPolicy.load(file);
            MinecraftPackTranslations.Snapshot packSnapshot =
                MinecraftPackTranslations.snapshot(server, next.translationLocale());

            BridgeRuntime active = runtime;
            if (active == null) {
                // Recover after an invalid/missing configuration at initial startup.
                startRuntime(server);
                if (runtime == null) {
                    source.sendFailure(Component.literal("DMCC reload failed; check server logs."));
                    return 0;
                }
                source.sendSuccess(() -> Component.literal(
                    "DMCC configuration loaded; connecting to Gateway."), false);
                return 1;
            }

            BridgeSettings previous = appliedSettings;
            boolean reconnect = previous == null || BridgeReloadPlan.requiresReconnect(previous, next);
            // Failed ownership-ledger reads reject the reload without changing
            // login privileges or abandoning the old connection.
            if (next.opSyncEnabled()) {
                opSyncApplier.configure(file.resolveSibling("minecraft-bridge-managed-ops.properties"));
            }

            // Commit validated local settings. Network teardown is deferred to
            // BridgeRuntime, never a blocking join on Minecraft's tick thread.
            appliedSettings = next;
            serverId = next.serverId();
            pendingRequestTtlMillis = next.pendingRequestTtlMillis();
            gracefulShutdownTimeoutMillis = next.gracefulShutdownTimeoutMillis();
            requireLinking = next.requireLinking();
            unlinkedPlayerAction = next.unlinkedPlayerAction();
            opSyncEnabled = next.opSyncEnabled();
            relayPlayerCommands = next.relayPlayerCommands();
            overwriteNativeMessages = next.overwriteNativeMessages();
            NativeMessageFormatter.configure(format);
            echoPlayerCommands = format.echoPlayerCommands();
            echoGameMode = format.echoGameMode();
            translationLocale = next.translationLocale();
            selectedPackTranslations = packSnapshot;
            if (!next.opSyncEnabled()) opSyncApplier.clear();
            if (reconnect || !next.requireLinking()
                || (previous != null && (previous.requireLinking() != next.requireLinking()
                    || !previous.unlinkedPlayerAction().equals(next.unlinkedPlayerAction())))) {
                loginGate.clearAll();
                freezeChecks.clearAll();
                frozenPlayers.clearAll();
                freezeSessions.clear();
                freezeCorrectedAt.clear();
                pendingLinkPlayers.clear();
                pendingUnlinkPlayers.clear();
            }
            statsWorker.execute(this::refreshTranslations);
            configureOfficialLanguageTask(file);
            if (reconnect) {
                active.reconfigure(() -> new BridgeClient(next,
                    (client, envelope) -> handleGatewayPacket(server, client, envelope)));
            }
            final String status = reconnect
                ? "DMCC configuration reloaded; reconnecting to Gateway."
                : "DMCC configuration reloaded; Gateway connection retained.";
            source.sendSuccess(() -> Component.literal(status), false);
            LOGGER.info("DMCC full configuration reload completed (reconnect={})", reconnect);
            return 1;
        } catch (IOException | RuntimeException invalid) {
            LOGGER.warn("DMCC configuration reload rejected; active settings retained ({})",
                invalid.getClass().getSimpleName());
            source.sendFailure(Component.literal(
                "DMCC reload failed; correct minecraft-bridge.properties and check server logs."));
            return 0;
        }
    }

    private int refreshLocalPresentation(MinecraftServer server) {'''
    text = replace_once(text, needle, new_method, fn)
    text = replace_once(text, '''        metricTickCounter = 0L;
        requireLinking = false;''',
                        '''        metricTickCounter = 0L;
        appliedSettings = null;
        requireLinking = false;''', fn)
    return text


def patch_neoforge(text: str) -> str:
    fn = 'NeoBridgeMod.java'
    text = replace_once(text, '    private BridgeRuntime runtime;\n    private BridgeSettings settings;',
                        '    private volatile BridgeRuntime runtime;\n    private volatile BridgeSettings settings;', fn)
    text = replace_once(text,
        '            this.minecraft = server;\n            this.settings = loaded;',
        '            if (loaded.opSyncEnabled()) {\n'
        '                operators.configure(config.resolveSibling("minecraft-bridge-managed-ops.properties"));\n'
        '            }\n'
        '            this.minecraft = server;\n            this.settings = loaded;', fn)
    text = replace_once(text,
        '            if (loaded.requireLinking()) {',
        '            if (!"fabric".equals(loaded.bridgeKind())) {\n'
        '                throw new ProtocolException("NeoForge backend requires bridge_kind=fabric");\n'
        '            }\n'
        '            if (loaded.requireLinking()) {', fn)
    text = replace_once(text,
        '() -> new BridgeClient(loaded, (client, packet) -> handlePacket(server, packet))',
        '() -> new BridgeClient(loaded, (client, packet) -> handlePacket(server, client, packet))', fn)
    text = replace_once(text,
        '                .then(literal("unlink").executes(ctx -> requestUnlink(ctx.getSource())))',
        '                .then(literal("unlink").executes(ctx -> requestUnlink(ctx.getSource())))\n'
        '                .then(literal("reload").requires(src -> src.hasPermission(4))\n'
        '                    .executes(ctx -> reloadLocalConfiguration(ctx.getSource())))', fn)
    needle = '    private int requestLink(CommandSourceStack source) throws CommandSyntaxException {'
    method = '''    /** Reload all NeoForge bridge connection settings without restarting Minecraft. */
    private int reloadLocalConfiguration(CommandSourceStack source) {
        MinecraftServer server = source.getServer();
        Path file = FMLPaths.CONFIGDIR.get().resolve("minecraft-bridge.properties");
        try {
            final BridgeSettings next;
            try (var reader = Files.newBufferedReader(file)) {
                next = BridgeSettings.fromReader(reader);
            }
            if (next.requireLinking()) {
                throw new ProtocolException("NeoForge login freeze/kick is unsupported");
            }
            if (!"fabric".equals(next.bridgeKind())) {
                throw new ProtocolException("NeoForge backend requires bridge_kind=fabric");
            }
            // Keep the running connection intact when the OP ledger is invalid.
            if (next.opSyncEnabled()) {
                operators.configure(file.resolveSibling("minecraft-bridge-managed-ops.properties"));
            }
            BridgeRuntime current = runtime;
            BridgeSettings old = settings;
            if (current == null) {
                minecraft = server;
                settings = next;
                runtime = new BridgeRuntime(
                    () -> new BridgeClient(next,
                        (client, packet) -> handlePacket(server, client, packet)),
                    1_000, 30_000, () -> sendStarted(server)
                );
                runtime.start();
                source.sendSuccess(() -> Component.literal(
                    "DMCC configuration loaded; connecting to Gateway."), false);
                return 1;
            }
            boolean reconnect = BridgeReloadPlan.requiresReconnect(old, next);
            settings = next;
            if (!next.opSyncEnabled()) operators.clear();
            if (reconnect) {
                pendingLinks.clear();
                current.reconfigure(() -> new BridgeClient(next,
                    (client, packet) -> handlePacket(server, client, packet)));
            }
            source.sendSuccess(() -> Component.literal(reconnect
                ? "DMCC configuration reloaded; reconnecting to Gateway."
                : "DMCC configuration reloaded; connection retained."), false);
            LOGGER.info("NeoForge Bridge configuration reloaded (reconnect={})", reconnect);
            return 1;
        } catch (IOException | RuntimeException invalid) {
            LOGGER.warn("NeoForge Bridge reload rejected; active settings retained", invalid);
            source.sendFailure(Component.literal(
                "DMCC reload failed; correct minecraft-bridge.properties and inspect logs."));
            return 0;
        }
    }

    private int requestLink(CommandSourceStack source) throws CommandSyntaxException {'''
    text = replace_once(text, needle, method, fn)
    text = replace_once(text,
        '    private void handlePacket(MinecraftServer server, ProtocolEnvelope packet) {\n'
        '        BridgeSettings configured = settings;\n        BridgeRuntime current = runtime;\n'
        '        if (configured == null || current == null || !packet.serverId().equals(configured.serverId())) return;',
        '    private void handlePacket(MinecraftServer server, BridgeClient client, ProtocolEnvelope packet) {\n'
        '        BridgeSettings configured = settings;\n        BridgeRuntime current = runtime;\n'
        '        if (configured == null || current == null || !current.isCurrentConnection(client)\n'
        '            || !packet.serverId().equals(configured.serverId())) return;', fn)
    text = replace_once(text,
        '            policy.ifPresent(value -> server.execute(() -> operators.apply(server, value)));',
        '            policy.ifPresent(value -> server.execute(() -> {\n'
        '                BridgeRuntime live = runtime;\n'
        '                if (live != null && live.isCurrentConnection(client)) operators.apply(server, value);\n'
        '            }));', fn)
    text = replace_once(text,
        '            server.execute(() -> {\n                DmccRconConsoleSource output = new DmccRconConsoleSource(server);',
        '            server.execute(() -> {\n'
        '                BridgeRuntime live = runtime;\n'
        '                if (live == null || !live.isCurrentConnection(client)) return;\n'
        '                DmccRconConsoleSource output = new DmccRconConsoleSource(server);', fn)
    return text


def patch_neoforge_gradle(text: str) -> str:
    filename = 'bridge/neoforge-bridge/build.gradle'
    text = replace_once(text,
        "'BridgeRuntime.java', 'BridgeSettings.java',",
        "'BridgeRuntime.java', 'BridgeSettings.java', 'BridgeReloadPlan.java',", filename)
    text = replace_once(text,
        "'BridgeRuntimeTest.java', 'BridgeSettingsTest.java',",
        "'BridgeRuntimeTest.java', 'BridgeSettingsTest.java', 'BridgeReloadPlanTest.java',", filename)
    return text


PLAN = '''package io.miki.dmcc.bridge;

/** Categorizes local-only settings separately from Gateway identity and transport. */
final class BridgeReloadPlan {
    private BridgeReloadPlan() { }

    static boolean requiresReconnect(BridgeSettings before, BridgeSettings after) {
        if (before == null || after == null) return true;
        return !before.serverId().equals(after.serverId())
            || !before.gatewayHost().equals(after.gatewayHost())
            || before.gatewayPort() != after.gatewayPort()
            || !before.authenticationSecret().equals(after.authenticationSecret())
            || before.connectTimeoutMillis() != after.connectTimeoutMillis()
            || before.authenticationTimeoutMillis() != after.authenticationTimeoutMillis()
            || before.readTimeoutMillis() != after.readTimeoutMillis()
            || !before.bridgeKind().equals(after.bridgeKind());
    }
}
'''

PLAN_TEST = '''package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.StringReader;
import org.junit.jupiter.api.Test;

/** Contract for safe DMCC live configuration reload routing. */
final class BridgeReloadPlanTest {
    private static final String BASE = """
        server_id=survival
        gateway_host=127.0.0.1
        gateway_port=8765
        authentication_secret=test-secret
        """;

    private static BridgeSettings read(String config) throws Exception {
        return BridgeSettings.fromReader(new StringReader(config));
    }

    @Test
    void presentationAndLinkOptionsDoNotReconnect() throws Exception {
        BridgeSettings base = read(BASE);
        assertFalse(BridgeReloadPlan.requiresReconnect(base, read(BASE + """
            translation_locale=zh_tw
            overwrite_native_messages=true
            require_linking=true
            unlinked_player_action=freeze
            op_sync_enabled=true
            pending_request_ttl_millis=30000
            """)));
    }

    @Test
    void IdentityCredentialsAndSocketSettingsRequireReconnect() throws Exception {
        BridgeSettings base = read(BASE);
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE.replace("server_id=survival", "server_id=creative"))));
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE.replace("test-secret", "new-secret"))));
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE.replace("gateway_port=8765", "gateway_port=9876"))));
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE + "read_timeout_millis=90000\\n")));
    }
}
'''

RUNTIME_TEST_APPEND = '''
    @Test
    void reconfigureWakesBackoffAndConnectsWithNewFactory() throws Exception {
        CountDownLatch firstFailed = new CountDownLatch(1);
        CountDownLatch secondConnected = new CountDownLatch(1);
        CountDownLatch keepConnected = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() throws IOException {
                firstFailed.countDown();
                throw new IOException("old gateway is offline");
            }
            @Override public void send(ProtocolEnvelope envelope) { }
            @Override public void awaitDisconnect() { }
            @Override public void close() { }
        }, 15_000, 15_000);
        runtime.start();
        try {
            assertTrue(firstFailed.await(2, TimeUnit.SECONDS));
            runtime.reconfigure(() -> new BridgeConnection() {
                @Override public void connect() { secondConnected.countDown(); }
                @Override public void send(ProtocolEnvelope envelope) { }
                @Override public void awaitDisconnect() throws InterruptedException {
                    keepConnected.await();
                }
                @Override public void close() { keepConnected.countDown(); }
            });
            // Before this change, the previous 15-second backoff blocked reload.
            assertTrue(secondConnected.await(2, TimeUnit.SECONDS));
        } finally {
            runtime.close();
        }
    }

    @Test
    void reconfigureRejectsOldQueuedPacketsWithoutLeakingToNewPeer() throws Exception {
        CountDownLatch firstConnected = new CountDownLatch(1);
        CountDownLatch firstSendStarted = new CountDownLatch(1);
        CountDownLatch releaseFirstSend = new CountDownLatch(1);
        CountDownLatch secondConnected = new CountDownLatch(1);
        CountDownLatch firstDisconnected = new CountDownLatch(1);
        CountDownLatch secondDisconnected = new CountDownLatch(1);
        AtomicInteger secondPeerPackets = new AtomicInteger();
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { firstConnected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) throws IOException {
                firstSendStarted.countDown();
                try {
                    releaseFirstSend.await(2, TimeUnit.SECONDS);
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    throw new IOException(exception);
                }
            }
            @Override public void awaitDisconnect() throws InterruptedException {
                firstDisconnected.await();
            }
            @Override public void close() { firstDisconnected.countDown(); }
        }, 1, 1);
        runtime.start();
        try {
            assertTrue(firstConnected.await(2, TimeUnit.SECONDS));
            var inFlight = runtime.sendRequired(new ProtocolEnvelope(
                1, "inflight", "survival", null, java.util.Map.of()));
            assertTrue(firstSendStarted.await(2, TimeUnit.SECONDS));
            var stale = runtime.sendRequired(new ProtocolEnvelope(
                1, "stale", "survival", null, java.util.Map.of()));
            runtime.reconfigure(() -> new BridgeConnection() {
                @Override public void connect() { secondConnected.countDown(); }
                @Override public void send(ProtocolEnvelope envelope) {
                    secondPeerPackets.incrementAndGet();
                }
                @Override public void awaitDisconnect() throws InterruptedException {
                    secondDisconnected.await();
                }
                @Override public void close() { secondDisconnected.countDown(); }
            });
            assertTrue(stale.isCompletedExceptionally());
            releaseFirstSend.countDown();
            assertTrue(secondConnected.await(2, TimeUnit.SECONDS));
            runtime.sendRequired(new ProtocolEnvelope(
                1, "current", "survival", null, java.util.Map.of()
            )).get(2, TimeUnit.SECONDS);
            assertEquals(1, secondPeerPackets.get());
            // An in-flight message may fail at the retired transport, but can
            // never be forwarded to the new generation.
            assertTrue(inFlight.isDone());
        } finally {
            releaseFirstSend.countDown();
            runtime.close();
        }
    }

'''


def patch_runtime_test(text: str) -> str:
    if not text.rstrip().endswith('}'):
        raise ValueError('BridgeRuntimeTest.java: expected closing class brace')
    head, last = text.rsplit('}', 1)
    if last.strip():
        raise ValueError('BridgeRuntimeTest.java: unknown content after closing brace')
    return head.rstrip() + '\n' + RUNTIME_TEST_APPEND + '}\n'


def patch_docs(text: str) -> str:
    section = '''\n### Minecraft Bridge `/dmcc reload` (OP 4)\n\n`/dmcc reload` re-reads **all** supported values in `config/minecraft-bridge.properties`.\nMalformed configuration is rejected without tearing down the previous\nconnection. Changes to the Gateway address, port, authentication, timeouts,\n`server_id`, or `bridge_kind` start an authenticated reconnect on the background\nBridge worker. Display, language, link policy, and OP-sync options are applied\nwithout reconnecting. In-flight requests from the old peer are discarded on\nreconnect. The target Gateway must already trust the new ID/secret; a syntactically\nvalid but wrong secret cannot be authenticated and will continue to retry.\n\nThe NeoForge 1.21.8 backend also supports `/dmcc reload` (OP 4) for its
supported properties; `require_linking=true` remains explicitly unsupported.

`/dmcc refresh` remains a Fabric display/language-only update (OP 3).\n`$dmcc reload` in Discord restarts the **Bot module**, which is separate.\nIf the mod JAR itself was replaced, a Minecraft server restart is still needed.\n\n'''
    if '### Minecraft Bridge `/dmcc reload` (OP 4)' in text:
        raise ValueError('docs/DMCC.md: reload docs already present')
    return text.rstrip() + '\n' + section.rstrip() + '\n'


def build_changes(root: Path) -> dict[Path, tuple[str | None, str]]:
    actions = {
        SRC / 'BridgeRuntime.java': patch_runtime,
        SRC / 'BridgeMod.java': patch_mod,
        Path('bridge/neoforge-bridge/src/main/java/io/miki/dmcc/bridge/NeoBridgeMod.java'): patch_neoforge,
        Path('bridge/neoforge-bridge/build.gradle'): patch_neoforge_gradle,
        TEST / 'BridgeRuntimeTest.java': patch_runtime_test,
        Path('docs/DMCC.md'): patch_docs,
    }
    updates: dict[Path, tuple[str | None, str]] = {}
    for relative, transform in actions.items():
        file = root / relative
        if not file.is_file():
            raise FileNotFoundError(f'Missing required repo file: {file}')
        old = file.read_text(encoding='utf-8')
        updates[relative] = (old, transform(old))
    for relative, source in {
        SRC / 'BridgeReloadPlan.java': PLAN,
        TEST / 'BridgeReloadPlanTest.java': PLAN_TEST,
    }.items():
        file = root / relative
        if file.exists():
            raise FileExistsError(f'Refusing to overwrite existing file: {file}')
        updates[relative] = (None, source)
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path, help='Path to local Discord-bot repository')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Print proposed unified diff without writing')
    action.add_argument('--apply', action='store_true', help='Apply source changes to checkout')
    args = parser.parse_args()
    root = args.repo.resolve()
    try:
        updates = build_changes(root)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f'Cannot prepare changes: {exc}', file=sys.stderr)
        return 1
    for relative, (old, new) in updates.items():
        if args.check:
            original = (old or '').splitlines(keepends=True)
            changed = new.splitlines(keepends=True)
            sys.stdout.writelines(difflib.unified_diff(
                original, changed, fromfile=f'a/{relative}', tofile=f'b/{relative}'
            ))
        else:
            dest = root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(new, encoding='utf-8')
            print(f'Updated {relative}')
    if args.apply:
        print('\nRun: cd <repo>/bridge/minecraft-bridge && ./gradlew test remapJar')
        print('Run again with -Pminecraft_version=1.21.9 -Pfabric_api_version=0.134.0+1.21.9')
        print('Run: python -m pytest -q (from repo root, with dependencies installed)')
    return 0


if __name__ == '__main__':
    sys.exit(main())