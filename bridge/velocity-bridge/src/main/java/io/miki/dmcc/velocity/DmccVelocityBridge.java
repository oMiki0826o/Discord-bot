package io.miki.dmcc.velocity;

import com.velocitypowered.api.command.CommandManager;
import com.velocitypowered.api.event.Subscribe;
import com.velocitypowered.api.event.connection.PostLoginEvent;
import com.velocitypowered.api.plugin.Plugin;
import com.velocitypowered.api.plugin.annotation.DataDirectory;
import com.velocitypowered.api.proxy.ProxyServer;
import io.miki.dmcc.bridge.BridgeClient;
import io.miki.dmcc.bridge.BridgeRuntime;
import io.miki.dmcc.bridge.BridgeSettings;
import io.miki.dmcc.bridge.ProtocolEnvelope;
import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import javax.inject.Inject;

/**
 * A deliberately small Velocity peer: it reports genuine proxy logins and
 * invokes only the installed global-whitelist command. Backend transfers do
 * not produce PostLoginEvent, so they cannot cause an avatar refresh.
 */
@Plugin(id = "dmcc-velocity-bridge", name = "DMCC Velocity Bridge", version = "0.3.0")
public final class DmccVelocityBridge implements AutoCloseable {
    private static final Pattern PLAYER_NAME = Pattern.compile("^[A-Za-z0-9_]{3,16}$");
    private final ProxyServer proxy;
    private final Path dataDirectory;
    private BridgeRuntime runtime;
    private String serverId;

    @Inject
    public DmccVelocityBridge(ProxyServer proxy, @DataDirectory Path dataDirectory) {
        this.proxy = proxy;
        this.dataDirectory = dataDirectory;
    }

    @Subscribe
    public void onProxyInitialize(com.velocitypowered.api.event.proxy.ProxyInitializeEvent event) {
        Path settingsPath = dataDirectory.resolve("bridge.properties");
        try (Reader reader = Files.newBufferedReader(settingsPath)) {
            BridgeSettings settings = BridgeSettings.fromReader(reader);
            this.serverId = settings.serverId();
            this.runtime = new BridgeRuntime(
                () -> new BridgeClient(settings, this::onGatewayPacket), 1_000, 30_000
            );
            runtime.start();
        } catch (IOException | RuntimeException exception) {
            throw new IllegalStateException("Unable to start DMCC Velocity Bridge", exception);
        }
    }

    @Subscribe
    public void onPostLogin(PostLoginEvent event) {
        if (runtime == null || serverId == null) return;
        var player = event.getPlayer();
        runtime.publishEvent(new ProtocolEnvelope(1, "proxy_player_login", serverId, null, Map.of(
            "minecraft_uuid", player.getUniqueId().toString(),
            "player_name", player.getUsername()
        )));
    }

    private void onGatewayPacket(BridgeClient client, ProtocolEnvelope envelope) {
        if (!"proxy_whitelist_request".equals(envelope.type())) return;
        String action = asText(envelope.data().get("action"));
        String playerName = asText(envelope.data().get("player_name"));
        if (!"add".equals(action) || playerName == null || !PLAYER_NAME.matcher(playerName).matches()) {
            respond(envelope, false, "invalid proxy whitelist request");
            return;
        }
        CommandManager commands = proxy.getCommandManager();
        CompletableFuture<Boolean> result = commands.executeAsync(
            proxy.getConsoleCommandSource(), "globalwhitelist add " + playerName
        );
        result.whenComplete((accepted, failure) -> {
            if (failure != null || !Boolean.TRUE.equals(accepted)) {
                respond(envelope, false, "globalwhitelist command was rejected");
            } else {
                respond(envelope, true, "Proxy whitelist update requested for " + playerName + ".");
            }
        });
    }

    private void respond(ProtocolEnvelope request, boolean ok, String output) {
        if (runtime == null || serverId == null || request.requestId() == null) return;
        runtime.publishEvent(new ProtocolEnvelope(1, "proxy_whitelist_response", serverId,
            request.requestId(), Map.of("ok", ok, ok ? "output" : "error", output)));
    }

    private static String asText(Object value) {
        return value instanceof String text && !text.isBlank() ? text : null;
    }

    @Override
    public void close() {
        if (runtime != null && serverId != null) {
            runtime.closeGracefully(
                new ProtocolEnvelope(1, "server_stopping", serverId, null, Map.of()),
                Duration.ofMillis(1_500)
            );
        }
    }
}
