package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

class FreezeRegistryTest {
    private final AtomicLong clock = new AtomicLong(1_000_000L);
    private final FreezeRegistry leases = new FreezeRegistry(clock::get, TimeUnit.MINUTES.toNanos(5));
    private final UUID uuid = UUID.fromString("123e4567-e89b-12d3-a456-426614174000");

    @Test
    void holdsOriginalAnchorUntilExplicitReleaseWithoutPersistingPlayerFlags() {
        var original = new FreezeRegistry.Anchor(3, 64, -10, 50, 15);
        leases.freeze(uuid, original);
        leases.freeze(uuid, new FreezeRegistry.Anchor(20, 65, -40, 60, 30));
        assertTrue(leases.isFrozen(uuid, true));
        assertEquals(original, leases.anchor(uuid));
        leases.release(uuid);
        assertFalse(leases.isFrozen(uuid, true));
    }

    @Test
    void serverDisconnectImmediatelyThawsPlayer() {
        leases.freeze(uuid, new FreezeRegistry.Anchor(0, 64, 0, 0, 0));
        assertFalse(leases.isFrozen(uuid, false));
        assertNull(leases.anchor(uuid));
    }

    @Test
    void leaseExpiresOpenEvenWhenBotKeepsAnswering() {
        leases.freeze(uuid, new FreezeRegistry.Anchor(0, 64, 0, 0, 0));
        clock.addAndGet(TimeUnit.MINUTES.toNanos(5) + 1);
        assertFalse(leases.isFrozen(uuid, true));
    }

    @Test
    void refusesNaNAndInfinityAnchors() {
        assertThrows(IllegalArgumentException.class, () ->
            leases.freeze(uuid, new FreezeRegistry.Anchor(Double.NaN, 0, 0, 0, 0))
        );
        assertThrows(IllegalArgumentException.class, () ->
            leases.freeze(uuid, new FreezeRegistry.Anchor(0, Double.POSITIVE_INFINITY, 0, 0, 0))
        );
    }
}
