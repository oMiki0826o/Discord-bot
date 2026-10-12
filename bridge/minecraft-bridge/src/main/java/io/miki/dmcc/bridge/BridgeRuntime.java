package io.miki.dmcc.bridge;

import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Runs blocking Bridge connection work away from Minecraft's server thread. */
public final class BridgeRuntime implements AutoCloseable {
    private static final Logger LOGGER = LoggerFactory.getLogger("minecraft_bridge/runtime");
    private final Supplier<BridgeConnection> connectionFactory;
    private final long initialDelayMillis;
    private final long maximumDelayMillis;
    private final Runnable connectedCallback;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "dmcc-bridge");
        thread.setDaemon(true);
        return thread;
    });
    private final ExecutorService sender = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "dmcc-bridge-sender");
        thread.setDaemon(true);
        return thread;
    });
    private final BlockingQueue<Outbound> outbound = new ArrayBlockingQueue<>(256);
    private final AtomicLong droppedEvents = new AtomicLong();
    private volatile boolean running;
    private volatile BridgeConnection connection;
    private volatile Throwable lastFailure;

    public BridgeRuntime(Supplier<BridgeConnection> connectionFactory, long initialDelayMillis, long maximumDelayMillis) {
        this(connectionFactory, initialDelayMillis, maximumDelayMillis, () -> { });
    }

    public BridgeRuntime(
        Supplier<BridgeConnection> connectionFactory,
        long initialDelayMillis,
        long maximumDelayMillis,
        Runnable connectedCallback
    ) {
        this.connectionFactory = connectionFactory;
        this.initialDelayMillis = initialDelayMillis;
        this.maximumDelayMillis = maximumDelayMillis;
        this.connectedCallback = connectedCallback;
    }

    public void start() {
        if (running) return;
        running = true;
        worker.execute(this::run);
        sender.execute(this::sendLoop);
    }

    public Throwable lastFailure() {
        return lastFailure;
    }

    /** Enqueue a best-effort Minecraft event without blocking the server thread. */
    public boolean publishEvent(ProtocolEnvelope envelope) {
        if (!running) return false;
        boolean accepted = outbound.offer(new Outbound(envelope, null));
        if (!accepted) droppedEvents.incrementAndGet();
        return accepted;
    }

    /** Enqueue a response whose caller needs an explicit success or failure signal. */
    public CompletableFuture<Void> sendRequired(ProtocolEnvelope envelope) {
        CompletableFuture<Void> result = new CompletableFuture<>();
        if (!running || !outbound.offer(new Outbound(envelope, result))) {
            result.completeExceptionally(new RejectedExecutionException("DMCC outbound queue is unavailable"));
        }
        return result;
    }

    public long droppedEvents() {
        return droppedEvents.get();
    }

    /** Sends a packet only while the current Bridge TCP client is authenticated. */
    public void send(ProtocolEnvelope envelope) throws IOException {
        BridgeConnection active = connection;
        if (active == null) {
            throw new IOException("DMCC Bridge is not connected");
        }
        if (active instanceof BridgeClient client && client.state() != BridgeClient.State.AUTHENTICATED) {
            throw new IOException("DMCC Bridge is not authenticated");
        }
        active.send(envelope);
    }

    private void run() {
        long delay = initialDelayMillis;
        while (running) {
            BridgeConnection candidate = null;
            try {
                candidate = connectionFactory.get();
                connection = candidate;
                candidate.connect();
                lastFailure = null;
                connectedCallback.run();
                delay = initialDelayMillis;
                candidate.awaitDisconnect();
                if (!running) return;
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception exception) {
                lastFailure = exception;
                if (running) {
                    LOGGER.warn("DMCC Bridge connection cycle failed", exception);
                }
                if (!running) return;
            } finally {
                if (candidate != null) candidate.close();
                if (connection == candidate) connection = null;
            }
            try {
                Thread.sleep(delay);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            }
            delay = Math.min(maximumDelayMillis, Math.max(delay * 2, 1));
        }
    }

    private void sendLoop() {
        while (running || !outbound.isEmpty()) {
            Outbound item;
            try {
                item = outbound.poll(200, TimeUnit.MILLISECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            }
            if (item == null) continue;
            try {
                send(item.envelope());
                if (item.result() != null) item.result().complete(null);
            } catch (IOException exception) {
                if (item.result() != null) item.result().completeExceptionally(exception);
                else lastFailure = exception;
            }
        }
    }

    @Override
    public void close() {
        running = false;
        BridgeConnection active = connection;
        if (active != null) active.close();
        worker.shutdownNow();
        sender.shutdownNow();
        IOException closed = new IOException("DMCC Bridge runtime is closed");
        Outbound pending;
        while ((pending = outbound.poll()) != null) {
            if (pending.result() != null) pending.result().completeExceptionally(closed);
        }
        try {
            worker.awaitTermination(2, TimeUnit.SECONDS);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            LOGGER.debug("Interrupted while waiting for DMCC Bridge worker shutdown", exception);
        }
    }

    private record Outbound(ProtocolEnvelope envelope, CompletableFuture<Void> result) { }
}
