package io.miki.dmcc.bridge;

import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Runs blocking Bridge connection work away from Minecraft's server thread. */
public final class BridgeRuntime implements AutoCloseable {
    private static final Logger LOGGER = LoggerFactory.getLogger("minecraft_bridge/runtime");
    private static final int REQUIRED_QUEUE_CAPACITY = 64;
    private static final int EVENT_QUEUE_CAPACITY = 256;
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
    private final BlockingQueue<Outbound> requiredOutbound;
    private final BlockingQueue<Outbound> eventOutbound;
    private final AtomicLong droppedEvents = new AtomicLong();
    private final AtomicBoolean acceptingEvents = new AtomicBoolean();
    private final AtomicBoolean closed = new AtomicBoolean();
    private volatile boolean running;
    private volatile BridgeConnection connection;
    private volatile Throwable lastFailure;
    private volatile Throwable lastSenderFailure;

    public BridgeRuntime(Supplier<BridgeConnection> connectionFactory, long initialDelayMillis, long maximumDelayMillis) {
        this(connectionFactory, initialDelayMillis, maximumDelayMillis, () -> { });
    }

    public BridgeRuntime(
        Supplier<BridgeConnection> connectionFactory,
        long initialDelayMillis,
        long maximumDelayMillis,
        Runnable connectedCallback
    ) {
        this(connectionFactory, initialDelayMillis, maximumDelayMillis, connectedCallback,
            REQUIRED_QUEUE_CAPACITY, EVENT_QUEUE_CAPACITY);
    }

    BridgeRuntime(
        Supplier<BridgeConnection> connectionFactory,
        long initialDelayMillis,
        long maximumDelayMillis,
        Runnable connectedCallback,
        int requiredCapacity,
        int eventCapacity
    ) {
        this.connectionFactory = connectionFactory;
        this.initialDelayMillis = initialDelayMillis;
        this.maximumDelayMillis = maximumDelayMillis;
        this.connectedCallback = connectedCallback;
        this.requiredOutbound = new ArrayBlockingQueue<>(requiredCapacity);
        this.eventOutbound = new ArrayBlockingQueue<>(eventCapacity);
    }

    public void start() {
        if (running) return;
        running = true;
        acceptingEvents.set(true);
        worker.execute(this::run);
        sender.execute(this::sendLoop);
    }

    public Throwable lastFailure() {
        return lastFailure;
    }

    /** Enqueue a best-effort Minecraft event without blocking the server thread. */
    public boolean publishEvent(ProtocolEnvelope envelope) {
        if (!running || !acceptingEvents.get()) return false;
        boolean accepted = eventOutbound.offer(new Outbound(envelope, null));
        if (!accepted) droppedEvents.incrementAndGet();
        return accepted;
    }

    /** Enqueue a response whose caller needs an explicit success or failure signal. */
    public CompletableFuture<Void> sendRequired(ProtocolEnvelope envelope) {
        CompletableFuture<Void> result = new CompletableFuture<>();
        if (!running || !requiredOutbound.offer(new Outbound(envelope, result))) {
            result.completeExceptionally(new RejectedExecutionException("DMCC outbound queue is unavailable"));
        }
        return result;
    }

    public long droppedEvents() {
        return droppedEvents.get();
    }

    public int requiredQueueDepth() {
        return requiredOutbound.size();
    }

    public int eventQueueDepth() {
        return eventOutbound.size();
    }

    public int requiredQueueCapacity() {
        return requiredOutbound.size() + requiredOutbound.remainingCapacity();
    }

    public int eventQueueCapacity() {
        return eventOutbound.size() + eventOutbound.remainingCapacity();
    }

    public Throwable lastSenderFailure() {
        return lastSenderFailure;
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
        while (running || !requiredOutbound.isEmpty() || !eventOutbound.isEmpty()) {
            Outbound item;
            try {
                item = requiredOutbound.poll();
                if (item == null) item = eventOutbound.poll(100, TimeUnit.MILLISECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            }
            if (item == null) continue;
            try {
                send(item.envelope());
                if (item.result() != null) item.result().complete(null);
            } catch (Exception exception) {
                lastSenderFailure = exception;
                if (item.result() != null) item.result().completeExceptionally(exception);
                else droppedEvents.incrementAndGet();
            }
        }
    }

    /** Flush one required lifecycle packet within a bounded deadline, then close. */
    public boolean closeGracefully(ProtocolEnvelope finalEnvelope, Duration timeout) {
        if (timeout.isNegative() || timeout.isZero()) {
            throw new IllegalArgumentException("graceful shutdown timeout must be positive");
        }
        acceptingEvents.set(false);
        CompletableFuture<Void> sent = sendRequired(finalEnvelope);
        boolean delivered = false;
        try {
            sent.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
            delivered = true;
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            lastSenderFailure = exception;
        } catch (ExecutionException | TimeoutException exception) {
            lastSenderFailure = exception;
        } finally {
            close();
        }
        return delivered;
    }

    @Override
    public void close() {
        if (!closed.compareAndSet(false, true)) return;
        acceptingEvents.set(false);
        running = false;
        BridgeConnection active = connection;
        if (active != null) active.close();
        worker.shutdownNow();
        sender.shutdownNow();
        IOException closed = new IOException("DMCC Bridge runtime is closed");
        failPending(requiredOutbound, closed);
        eventOutbound.clear();
        awaitTermination(worker, "connection");
        awaitTermination(sender, "sender");
    }

    private static void failPending(BlockingQueue<Outbound> queue, IOException failure) {
        Outbound pending;
        while ((pending = queue.poll()) != null) {
            if (pending.result() != null) pending.result().completeExceptionally(failure);
        }
    }

    private static void awaitTermination(ExecutorService executor, String name) {
        try {
            executor.awaitTermination(2, TimeUnit.SECONDS);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            LOGGER.debug("Interrupted while waiting for DMCC Bridge {} worker shutdown", name, exception);
        }
    }

    private record Outbound(ProtocolEnvelope envelope, CompletableFuture<Void> result) { }
}
