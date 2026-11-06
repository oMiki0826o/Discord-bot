package io.miki.dmcc.bridge;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;

/**
 * Non-persistent freeze leases: never writes invulnerability or game mode to player NBT.
 * Disconnect and bounded timeout both fail open.
 */
final class FreezeRegistry {
    record Anchor(double x, double y, double z, float yaw, float pitch) {
        Anchor {
            if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)
                || !Float.isFinite(yaw) || !Float.isFinite(pitch)) {
                throw new IllegalArgumentException("freeze anchor must contain finite coordinates");
            }
        }
    }

    private record Lease(Anchor anchor, long startedNanos) { }

    private final Map<UUID, Lease> frozen = new ConcurrentHashMap<>();
    private final LongSupplier clock;
    private final long maxLeaseNanos;

    FreezeRegistry(LongSupplier clock, long maxLeaseNanos) {
        if (maxLeaseNanos <= 0) throw new IllegalArgumentException("lease timeout must be positive");
        this.clock = clock;
        this.maxLeaseNanos = maxLeaseNanos;
    }

    void freeze(UUID uuid, Anchor anchor) {
        if (uuid == null || anchor == null) throw new IllegalArgumentException("missing player anchor");
        frozen.putIfAbsent(uuid, new Lease(anchor, clock.getAsLong()));
    }

    boolean isFrozen(UUID uuid, boolean gatewayAvailable) {
        if (uuid == null) return false;
        Lease lease = frozen.get(uuid);
        if (lease == null) return false;
        if (!gatewayAvailable || clock.getAsLong() - lease.startedNanos > maxLeaseNanos) {
            frozen.remove(uuid, lease);
            return false;
        }
        return true;
    }

    Anchor anchor(UUID uuid) {
        Lease lease = frozen.get(uuid);
        return lease == null ? null : lease.anchor;
    }

    void release(UUID uuid) {
        frozen.remove(uuid);
    }

    void clearAll() {
        frozen.clear();
    }
}
