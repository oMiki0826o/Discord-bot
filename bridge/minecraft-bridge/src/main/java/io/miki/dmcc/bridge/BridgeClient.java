/*
 * TCP client responsible only for the DMCC Gateway connection and handshake.
 */
package io.miki.dmcc.bridge;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Blocking network client intended to be called from a dedicated Bridge worker, never Fabric's main thread. */
public final class BridgeClient implements BridgeConnection {
    private static final int MAX_FRAME_BYTES = 262_144;
    private static final Logger LOGGER = LoggerFactory.getLogger("minecraft_bridge/client");

    /** Observable connection state for lifecycle and future reconnect logic. */
    public enum State { DISCONNECTED, CONNECTING, AUTHENTICATED }

    private final BridgeSettings settings;
    private final BridgeMessageHandler messageHandler;
    private final ExecutorService receiver = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "dmcc-bridge-receiver");
        thread.setDaemon(true);
        return thread;
    });
    private final CountDownLatch disconnected = new CountDownLatch(1);
    private final Object lifecycleLock = new Object();
    private final Object writeLock = new Object();
    private volatile Socket socket;
    private volatile State state = State.DISCONNECTED;
    private volatile Throwable lastFailure;

    public BridgeClient(BridgeSettings settings) {
        this(settings, (client, envelope) -> { });
    }

    public BridgeClient(BridgeSettings settings, BridgeMessageHandler messageHandler) {
        this.settings = settings;
        this.messageHandler = messageHandler;
    }

    public State state() {
        return state;
    }

    public Throwable lastFailure() {
        return lastFailure;
    }

    /** Opens one connection and completes the Protocol v1 HMAC handshake synchronously. */
    public void connect() throws IOException {
        synchronized (lifecycleLock) {
            if (state != State.DISCONNECTED) {
                throw new IllegalStateException("Bridge client is already connected");
            }
            state = State.CONNECTING;
            lastFailure = null;
        }
        try {
            Socket opened = new Socket();
            opened.connect(
                new InetSocketAddress(settings.gatewayHost(), settings.gatewayPort()),
                settings.connectTimeoutMillis()
            );
            opened.setSoTimeout(settings.authenticationTimeoutMillis());
            synchronized (lifecycleLock) {
                if (state != State.CONNECTING) {
                    opened.close();
                    throw new IOException("Bridge connection was closed during startup");
                }
                socket = opened;
            }
            send(new ProtocolEnvelope(1, "handshake", settings.serverId(), null, Map.of("bridge_version", "0.2.3")));
            ProtocolEnvelope challenge = receive();
            if (!challenge.type().equals("challenge")) {
                throw new ProtocolException("expected challenge from gateway");
            }
            Object rawChallenge = challenge.data().get("challenge");
            if (!(rawChallenge instanceof String value) || value.isBlank()) {
                throw new ProtocolException("gateway challenge is missing");
            }
            send(new ProtocolEnvelope(1, "authenticate", settings.serverId(), null,
                Map.of("response", Authentication.createResponse(value, settings.authenticationSecret()))));
            ProtocolEnvelope result = receive();
            if (!result.type().equals("login_success")) {
                throw new ProtocolException("gateway rejected Bridge authentication");
            }
            opened.setSoTimeout(settings.readTimeoutMillis());
            synchronized (lifecycleLock) {
                if (socket == null) {
                    throw new IOException("Bridge connection closed during authentication");
                }
                state = State.AUTHENTICATED;
            }
            receiver.execute(this::receiveLoop);
        } catch (IOException | RuntimeException exception) {
            lastFailure = exception;
            close();
            throw exception;
        }
    }

    public void send(ProtocolEnvelope envelope) throws IOException {
        byte[] frame = FrameCodec.encode(envelope.toJson().getBytes(StandardCharsets.UTF_8), MAX_FRAME_BYTES);
        Socket active;
        synchronized (lifecycleLock) {
            active = socket;
            if (active == null || active.isClosed()) {
                throw new IOException("DMCC Bridge connection is closed");
            }
        }
        synchronized (writeLock) {
            if (active.isClosed()) {
                throw new IOException("DMCC Bridge connection is closed");
            }
            OutputStream output = active.getOutputStream();
            output.write(frame);
            output.flush();
        }
    }

    @Override
    public void awaitDisconnect() throws InterruptedException {
        disconnected.await();
    }

    private ProtocolEnvelope receive() throws IOException {
        Socket active = socket;
        if (active == null || active.isClosed()) {
            throw new IOException("DMCC Bridge connection is closed");
        }
        InputStream input = active.getInputStream();
        byte[] header = input.readNBytes(4);
        if (header.length != 4) {
            throw new IOException("gateway closed before a frame header");
        }
        int size = ByteBuffer.wrap(header).getInt();
        if (size < 0 || size > MAX_FRAME_BYTES) {
            throw new ProtocolException("gateway frame exceeds configured limit");
        }
        byte[] payload = input.readNBytes(size);
        if (payload.length != size) {
            throw new IOException("gateway closed before a complete frame");
        }
        return ProtocolEnvelope.fromJson(new String(payload, StandardCharsets.UTF_8));
    }

    private void receiveLoop() {
        try {
            while (state == State.AUTHENTICATED) {
                ProtocolEnvelope envelope = receive();
                if (envelope.type().equals("ping")) {
                    send(new ProtocolEnvelope(1, "pong", settings.serverId(), envelope.requestId(), envelope.data()));
                } else {
                    messageHandler.handle(this, envelope);
                }
            }
        } catch (IOException exception) {
            if (state == State.AUTHENTICATED) {
                lastFailure = exception;
                LOGGER.warn("DMCC gateway connection ended for server {}", settings.serverId(), exception);
            }
        } catch (RuntimeException exception) {
            lastFailure = exception;
            LOGGER.error("DMCC message handler failed for server {}", settings.serverId(), exception);
        } finally {
            close();
        }
    }

    @Override
    public void close() {
        Socket active;
        synchronized (lifecycleLock) {
            state = State.DISCONNECTED;
            active = socket;
            socket = null;
        }
        if (active != null) {
            try {
                active.close();
            } catch (IOException exception) {
                LOGGER.debug("Unable to close DMCC socket for server {}", settings.serverId(), exception);
            }
        }
        receiver.shutdownNow();
        disconnected.countDown();
    }
}
