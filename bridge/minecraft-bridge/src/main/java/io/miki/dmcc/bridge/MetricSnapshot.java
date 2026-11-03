package io.miki.dmcc.bridge;

import java.util.Map;

/** Immutable and validated telemetry for the authenticated Minecraft gateway. */
final class MetricSnapshot {
    private MetricSnapshot() { }

    static Map<String, Object> from(double mspt, int onlinePlayers, int maxPlayers) {
        if (!Double.isFinite(mspt) || mspt < 0.0 || mspt > 2000.0) {
            throw new IllegalArgumentException("MSPT must be finite and within supported bounds");
        }
        if (onlinePlayers < 0 || maxPlayers < 0 || onlinePlayers > maxPlayers) {
            throw new IllegalArgumentException("Player counts are inconsistent");
        }
        double tps = mspt <= 0.0 ? 20.0 : Math.min(20.0, 1000.0 / mspt);
        return Map.of(
            "mspt", mspt,
            "tps", tps,
            "online_players", onlinePlayers,
            "max_players", maxPlayers
        );
    }
}
