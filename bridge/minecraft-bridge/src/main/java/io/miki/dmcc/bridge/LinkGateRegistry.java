package io.miki.dmcc.bridge;

import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;
import java.util.function.LongSupplier;
import java.util.Map;

/**
 * Fail-open state machine for authenticated pre-login link checks.
 *
 * Never blocks a Minecraft server thread with network I/O. A timeout, failed
 * queue submission or unavailable Gateway always returns ALLOW.
 */
final class LinkGateRegistry {
    enum Verdict { ALLOW, WAIT, DENY }
    record Decision(Verdict verdict, String code) {
        static Decision allow() { return new Decision(Verdict.ALLOW, ""); }
        static Decision waitForBot() { return new Decision(Verdict.WAIT, ""); }
    }

    private final LongSupplier clock;
    private final long timeoutNanos;
    private final Map<UUID, Pending> pending = new ConcurrentHashMap<>();

    LinkGateRegistry(LongSupplier clock, long timeoutNanos) {
        if (timeoutNanos < 1_000_000L || timeoutNanos > 10_000_000_000L) {
            throw new IllegalArgumentException("invalid login verification timeout");
        }
        this.clock = clock;
        this.timeoutNanos = timeoutNanos;
    }

    Decision poll(
        UUID uuid, Object connection, boolean bridgeAvailable,
        Function<String, Boolean> issueRequest
    ) {
        if (uuid == null || connection == null || !bridgeAvailable) {
            if (uuid != null) pending.remove(uuid);
            return Decision.allow();
        }
        Pending current = pending.get(uuid);
        if (current != null && current.connection != connection) {
            pending.remove(uuid, current);
            current = null;
        }
        if (current != null) {
            if (clock.getAsLong() - current.startedNanos >= timeoutNanos) {
                pending.remove(uuid, current);
                return Decision.allow();
            }
            if (current.linked == null) return Decision.waitForBot();
            if (current.linked) {
                pending.remove(uuid, current);
                return Decision.allow();
            }
            return new Decision(Verdict.DENY, current.code);
        }
        if (pending.size() > 512) {
            long now = clock.getAsLong();
            pending.entrySet().removeIf(entry ->
                now - entry.getValue().startedNanos >= timeoutNanos);
            if (pending.size() > 512) return Decision.allow();
        }
        Pending created = new Pending(connection, UUID.randomUUID().toString(), clock.getAsLong());
        pending.put(uuid, created);
        boolean submitted = false;
        try {
            submitted = Boolean.TRUE.equals(issueRequest.apply(created.requestId));
        } catch (RuntimeException ignored) {
            // A failed gateway must never prevent the vanilla login.
        }
        if (!submitted) {
            pending.remove(uuid, created);
            return Decision.allow();
        }
        return Decision.waitForBot();
    }

    boolean respond(UUID uuid, String requestId, boolean linked, String code) {
        if (uuid == null || requestId == null) return false;
        Pending current = pending.get(uuid);
        if (current == null || !current.requestId.equals(requestId)) return false;
        if (!linked && (code == null || !code.matches("[A-HJ-NP-Z2-9]{6}"))) return false;
        if (clock.getAsLong() - current.startedNanos >= timeoutNanos) return false;
        current.code = linked ? "" : code;
        current.linked = linked;
        return true;
    }

    void clear(UUID uuid) {
        pending.remove(uuid);
    }

    void clearAll() {
        pending.clear();
    }

    private static final class Pending {
        final Object connection;
        final String requestId;
        final long startedNanos;
        volatile Boolean linked;
        volatile String code = "";

        Pending(Object connection, String requestId, long startedNanos) {
            this.connection = connection;
            this.requestId = requestId;
            this.startedNanos = startedNanos;
        }
    }
}
