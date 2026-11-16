package io.miki.dmcc.bridge;

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
