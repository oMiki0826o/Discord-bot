/*
 * Owns the file-level configuration required for one Fabric server to find and
 * authenticate against one Python DMCC Gateway.
 */
package io.miki.dmcc.bridge;

import java.io.IOException;
import java.io.Reader;
import java.util.Properties;

/** Validated, immutable local settings for a single Minecraft Bridge instance. */
public record BridgeSettings(
    String serverId,
    String gatewayHost,
    int gatewayPort,
    String authenticationSecret,
    int connectTimeoutMillis,
    int authenticationTimeoutMillis,
    int readTimeoutMillis,
    long pendingRequestTtlMillis,
    int gracefulShutdownTimeoutMillis,
    boolean requireLinking,
    String unlinkedPlayerAction,
    boolean opSyncEnabled
) {
    public BridgeSettings(String serverId, String gatewayHost, int gatewayPort, String authenticationSecret) {
        this(serverId, gatewayHost, gatewayPort, authenticationSecret, 5_000, 15_000, 60_000, 120_000, 1_500, false, "kick", false);
    }

    /** Backward-compatible constructor for callers predating optional link enforcement. */
    public BridgeSettings(
        String serverId, String gatewayHost, int gatewayPort, String authenticationSecret,
        int connectTimeoutMillis, int authenticationTimeoutMillis, int readTimeoutMillis,
        long pendingRequestTtlMillis, int gracefulShutdownTimeoutMillis
    ) {
        this(
            serverId, gatewayHost, gatewayPort, authenticationSecret,
            connectTimeoutMillis, authenticationTimeoutMillis, readTimeoutMillis,
            pendingRequestTtlMillis, gracefulShutdownTimeoutMillis, false, "kick", false
        );
    }

    /** Preserves 1.21.8/1.21.9 old configuration constructors. */
    public BridgeSettings(
        String serverId, String gatewayHost, int gatewayPort, String authenticationSecret,
        int connectTimeoutMillis, int authenticationTimeoutMillis, int readTimeoutMillis,
        long pendingRequestTtlMillis, int gracefulShutdownTimeoutMillis,
        boolean requireLinking, String unlinkedPlayerAction
    ) {
        this(serverId, gatewayHost, gatewayPort, authenticationSecret,
            connectTimeoutMillis, authenticationTimeoutMillis, readTimeoutMillis,
            pendingRequestTtlMillis, gracefulShutdownTimeoutMillis,
            requireLinking, unlinkedPlayerAction, false);
    }

    /** Parses a standard Java properties stream without doing filesystem I/O. */
    public static BridgeSettings fromReader(Reader reader) throws IOException {
        Properties properties = new Properties();
        properties.load(reader);

        String serverId = required(properties, "server_id");
        String gatewayHost = required(properties, "gateway_host");
        String secret = required(properties, "authentication_secret");
        if (!gatewayHost.equals("127.0.0.1") && !gatewayHost.equals("localhost")) {
            throw new ProtocolException("gateway_host must be localhost or 127.0.0.1");
        }
        int gatewayPort;
        try {
            gatewayPort = Integer.parseInt(required(properties, "gateway_port"));
        } catch (NumberFormatException exception) {
            throw new ProtocolException("gateway_port must be an integer", exception);
        }
        if (gatewayPort < 1 || gatewayPort > 65535) {
            throw new ProtocolException("gateway_port must be between 1 and 65535");
        }
        return new BridgeSettings(
            serverId,
            gatewayHost,
            gatewayPort,
            secret,
            positiveInt(properties, "connect_timeout_millis", 5_000),
            positiveInt(properties, "authentication_timeout_millis", 15_000),
            positiveInt(properties, "read_timeout_millis", 60_000),
            positiveInt(properties, "pending_request_ttl_millis", 120_000),
            positiveInt(properties, "graceful_shutdown_timeout_millis", 1_500),
            strictBoolean(properties, "require_linking", false),
            unlinkedAction(properties),
            strictBoolean(properties, "op_sync_enabled", false)
        );
    }

    private static boolean strictBoolean(Properties properties, String key, boolean fallback) {
        String value = properties.getProperty(key);
        if (value == null || value.isBlank()) return fallback;
        if (value.equals("true")) return true;
        if (value.equals("false")) return false;
        throw new ProtocolException(key + " must be true or false");
    }

    private static String unlinkedAction(Properties properties) {
        String action = properties.getProperty("unlinked_player_action", "kick").trim();
        if (!action.equals("kick") && !action.equals("freeze")) {
            throw new ProtocolException("unlinked_player_action must be kick or freeze");
        }
        return action;
    }

    private static String required(Properties properties, String key) {
        String value = properties.getProperty(key);
        if (value == null || value.isBlank()) {
            throw new ProtocolException(key + " must be non-empty");
        }
        return value.trim();
    }

    private static int positiveInt(Properties properties, String key, int fallback) {
        String raw = properties.getProperty(key);
        if (raw == null || raw.isBlank()) return fallback;
        try {
            int value = Integer.parseInt(raw.trim());
            if (value < 1) throw new NumberFormatException();
            return value;
        } catch (NumberFormatException exception) {
            throw new ProtocolException(key + " must be a positive integer", exception);
        }
    }
}
