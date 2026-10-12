package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.CompletableFuture;
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

    @Test
    void publishesEventsOnTheDedicatedSenderInOrder() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch sent = new CountDownLatch(2);
        java.util.List<String> types = new java.util.concurrent.CopyOnWriteArrayList<>();
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { connected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) { types.add(envelope.type()); sent.countDown(); }
            @Override public void awaitDisconnect() throws InterruptedException { Thread.sleep(5_000); }
            @Override public void close() { }
        }, 1, 1);

        runtime.start();
        try {
            assertTrue(connected.await(1, TimeUnit.SECONDS));
            assertTrue(runtime.publishEvent(new ProtocolEnvelope(1, "first", "server", null, java.util.Map.of())));
            CompletableFuture<Void> required = runtime.sendRequired(
                new ProtocolEnvelope(1, "second", "server", "request", java.util.Map.of())
            );
            required.get(1, TimeUnit.SECONDS);
            assertTrue(sent.await(1, TimeUnit.SECONDS));
            assertEquals(java.util.List.of("first", "second"), types);
        } finally {
            runtime.close();
        }
    }

    @Test
    void rejectsOverflowWithoutBlockingTheCaller() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch releaseSend = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { connected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) throws IOException {
                try {
                    releaseSend.await();
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    throw new IOException("send interrupted", exception);
                }
            }
            @Override public void awaitDisconnect() throws InterruptedException { Thread.sleep(5_000); }
            @Override public void close() { releaseSend.countDown(); }
        }, 1, 1);

        runtime.start();
        try {
            assertTrue(connected.await(1, TimeUnit.SECONDS));
            int rejected = 0;
            long started = System.nanoTime();
            for (int index = 0; index < 400; index++) {
                if (!runtime.publishEvent(new ProtocolEnvelope(
                    1, "event", "server", null, java.util.Map.of("index", index)
                ))) rejected++;
            }
            long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
            assertTrue(rejected > 0);
            assertTrue(runtime.droppedEvents() > 0);
            assertTrue(elapsedMillis < 500);
        } finally {
            runtime.close();
        }
    }

    @Test
    void packetFailureDoesNotTerminateSenderWorker() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch keepConnected = new CountDownLatch(1);
        CountDownLatch normalSent = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { connected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) {
                if (envelope.type().equals("oversized")) throw new ProtocolException("payload too large");
                normalSent.countDown();
            }
            @Override public void awaitDisconnect() throws InterruptedException { keepConnected.await(); }
            @Override public void close() { keepConnected.countDown(); }
        }, 1, 1);

        runtime.start();
        try {
            assertTrue(connected.await(1, TimeUnit.SECONDS));
            CompletableFuture<Void> failed = runtime.sendRequired(
                new ProtocolEnvelope(1, "oversized", "server", "bad", java.util.Map.of())
            );
            CompletableFuture<Void> succeeded = runtime.sendRequired(
                new ProtocolEnvelope(1, "normal", "server", "good", java.util.Map.of())
            );
            org.junit.jupiter.api.Assertions.assertThrows(
                java.util.concurrent.ExecutionException.class,
                () -> failed.get(1, TimeUnit.SECONDS)
            );
            succeeded.get(1, TimeUnit.SECONDS);
            assertTrue(normalSent.await(1, TimeUnit.SECONDS));
            assertEquals("payload too large", runtime.lastSenderFailure().getMessage());
        } finally {
            runtime.close();
        }
    }

    @Test
    void requiredTrafficHasReservedCapacityDuringEventFlood() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch releaseFirst = new CountDownLatch(1);
        CountDownLatch requiredSent = new CountDownLatch(1);
        AtomicInteger sends = new AtomicInteger();
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { connected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) throws IOException {
                if (sends.getAndIncrement() == 0) {
                    try {
                        releaseFirst.await();
                    } catch (InterruptedException exception) {
                        Thread.currentThread().interrupt();
                        throw new IOException(exception);
                    }
                }
                if (envelope.type().equals("required")) requiredSent.countDown();
            }
            @Override public void awaitDisconnect() throws InterruptedException { Thread.sleep(5_000); }
            @Override public void close() { releaseFirst.countDown(); }
        }, 1, 1, () -> { }, 2, 2);

        runtime.start();
        try {
            assertTrue(connected.await(1, TimeUnit.SECONDS));
            for (int index = 0; index < 10; index++) {
                runtime.publishEvent(new ProtocolEnvelope(1, "event", "server", null, java.util.Map.of()));
            }
            CompletableFuture<Void> required = runtime.sendRequired(
                new ProtocolEnvelope(1, "required", "server", "request", java.util.Map.of())
            );
            releaseFirst.countDown();
            required.get(1, TimeUnit.SECONDS);
            assertTrue(requiredSent.await(1, TimeUnit.SECONDS));
            assertTrue(runtime.droppedEvents() > 0);
            assertEquals(2, runtime.requiredQueueCapacity());
            assertEquals(2, runtime.eventQueueCapacity());
        } finally {
            runtime.close();
        }
    }

    @Test
    void gracefulCloseFlushesFinalLifecyclePacket() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch stoppingSent = new CountDownLatch(1);
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { connected.countDown(); }
            @Override public void send(ProtocolEnvelope envelope) {
                if (envelope.type().equals("server_stopping")) stoppingSent.countDown();
            }
            @Override public void awaitDisconnect() throws InterruptedException { Thread.sleep(5_000); }
            @Override public void close() { }
        }, 1, 1);

        runtime.start();
        assertTrue(connected.await(1, TimeUnit.SECONDS));
        assertTrue(runtime.closeGracefully(
            new ProtocolEnvelope(1, "server_stopping", "server", null, java.util.Map.of()),
            Duration.ofSeconds(1)
        ));
        assertTrue(stoppingSent.await(1, TimeUnit.SECONDS));
        assertFalse(runtime.publishEvent(
            new ProtocolEnvelope(1, "late", "server", null, java.util.Map.of())
        ));
    }
}
