package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class LinkGateRegistryTest {
    private final AtomicLong nanos = new AtomicLong(100_000);
    private final LinkGateRegistry checks = new LinkGateRegistry(nanos::get, 5_000_000_000L);
    private final UUID player = UUID.fromString("123e4567-e89b-12d3-a456-426614174000");

    @Test
    void neverBlocksOnDisconnectedGateway() {
        assertEquals(LinkGateRegistry.Verdict.ALLOW,
            checks.poll(player, new Object(), false, id -> {
                fail("offline server must never request a link check");
                return false;
            }).verdict());
    }

    @Test
    void requestOnceAndVerifyMatchingAuthenticatedResponse() {
        Object connection = new Object();
        AtomicReference<String> sent = new AtomicReference<>();
        var first = checks.poll(player, connection, true, id -> {
            sent.set(id);
            return true;
        });
        assertEquals(LinkGateRegistry.Verdict.WAIT, first.verdict());
        assertEquals(LinkGateRegistry.Verdict.WAIT,
            checks.poll(player, connection, true, id -> {
                fail("must not send duplicate requests");
                return false;
            }).verdict());
        assertFalse(checks.respond(player, "wrong-id", true, null));
        assertTrue(checks.respond(player, sent.get(), true, null));
        assertEquals(LinkGateRegistry.Verdict.ALLOW,
            checks.poll(player, connection, true, id -> true).verdict());
    }

    @Test
    void rejectOnlyWithValidCodeAndMatchingSession() {
        Object connection = new Object();
        AtomicReference<String> id = new AtomicReference<>();
        checks.poll(player, connection, true, requestId -> {
            id.set(requestId);
            return true;
        });
        assertFalse(checks.respond(player, id.get(), false, "NOT A CODE"));
        assertTrue(checks.respond(player, id.get(), false, "ABCDEF"));
        var denied = checks.poll(player, connection, true, ignored -> true);
        assertEquals(LinkGateRegistry.Verdict.DENY, denied.verdict());
        assertEquals("ABCDEF", denied.code());
        assertEquals(LinkGateRegistry.Verdict.WAIT,
            checks.poll(player, new Object(), true, ignored -> true).verdict());
    }

    @Test
    void timesOutFailOpenAndNeverRechecksOneSession() {
        Object connection = new Object();
        checks.poll(player, connection, true, ignored -> true);
        nanos.addAndGet(5_000_000_001L);
        assertEquals(LinkGateRegistry.Verdict.ALLOW,
            checks.poll(player, connection, true, ignored -> {
                fail("must fail open rather than loop on expired request");
                return false;
            }).verdict());
    }

    @Test
    void sendFailureImmediatelyFailsOpen() {
        assertEquals(LinkGateRegistry.Verdict.ALLOW,
            checks.poll(player, new Object(), true, ignored -> false).verdict());
    }
}
