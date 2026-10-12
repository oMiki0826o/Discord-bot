package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

/** Verifies lifecycle work happens off-thread and is released during shutdown. */
final class BridgeRuntimeTest {
    @Test
    void startsTheConnectionWorkerAndClosesItOnShutdown() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch closed = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { connected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) { }
            @Override public void awaitDisconnect() throws InterruptedException { closed.await(); }
            @Override public void close() { closed.countDown(); }
        }, 1, 1);

        runtime.start();
        assertTrue(connected.await(1, TimeUnit.SECONDS));
        runtime.close();
        assertTrue(closed.await(1, TimeUnit.SECONDS));
    }

    @Test
    void reconnectsAfterAnEstablishedConnectionCloses() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        CountDownLatch secondAttempt = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            private final int attempt = attempts.incrementAndGet();

            @Override public void connect() { }
            @Override public void send(ProtocolEnvelope envelope) throws IOException { }
            @Override public void awaitDisconnect() {
                if (attempt == 1) return;
                secondAttempt.countDown();
                try { Thread.sleep(1_000); } catch (InterruptedException exception) { Thread.currentThread().interrupt(); }
            }
            @Override public void close() { }
        }, 1, 2);

        runtime.start();
        try {
            assertTrue(secondAttempt.await(1, TimeUnit.SECONDS));
        } finally {
            runtime.close();
        }
    }

    @Test
    void invokesConnectedCallbackOnlyAfterTheConnectionAuthenticates() throws Exception {
        CountDownLatch connectedCallback = new CountDownLatch(1);
        CountDownLatch closed = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { }
            @Override public void send(ProtocolEnvelope envelope) { }
            @Override public void awaitDisconnect() throws InterruptedException { closed.await(); }
            @Override public void close() { closed.countDown(); }
        }, 1, 1, connectedCallback::countDown);

        runtime.start();
        try {
            assertTrue(connectedCallback.await(1, TimeUnit.SECONDS));
        } finally {
            runtime.close();
        }
    }

    @Test
    void exposesConnectionFailureForDiagnostics() throws Exception {
        CountDownLatch attempted = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() throws IOException {
                attempted.countDown();
                throw new IOException("gateway unavailable");
            }
            @Override public void send(ProtocolEnvelope envelope) { }
            @Override public void awaitDisconnect() { }
            @Override public void close() { }
        }, 100, 100);

        runtime.start();
        try {
            assertTrue(attempted.await(1, TimeUnit.SECONDS));
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1);
            while (runtime.lastFailure() == null && System.nanoTime() < deadline) {
                Thread.sleep(10);
            }
            assertEquals("gateway unavailable", runtime.lastFailure().getMessage());
        } finally {
            runtime.close();
        }
    }
}
