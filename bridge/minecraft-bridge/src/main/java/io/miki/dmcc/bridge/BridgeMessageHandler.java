package io.miki.dmcc.bridge;

/** Receives authenticated Gateway packets on the Bridge network worker. */
@FunctionalInterface
public interface BridgeMessageHandler {
    void handle(BridgeClient client, ProtocolEnvelope envelope);
}
