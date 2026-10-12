package io.miki.dmcc.bridge;

import java.io.IOException;

/** Minimal lifecycle contract that keeps reconnect orchestration independent of TCP details. */
public interface BridgeConnection extends AutoCloseable {
    void connect() throws IOException;

    void send(ProtocolEnvelope envelope) throws IOException;

    /** Blocks until this established connection has closed. */
    void awaitDisconnect() throws InterruptedException;

    @Override
    void close();
}
