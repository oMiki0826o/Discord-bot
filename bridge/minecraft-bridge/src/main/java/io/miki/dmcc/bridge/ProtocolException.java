/*
 * test_mod/minecraft-bridge/src/main/java/io/miki/dmcc/bridge/ProtocolException.java
 *
 * Represents malformed or unsafe DMCC Protocol v1 data received from a peer.
 */
package io.miki.dmcc.bridge;

public final class ProtocolException extends RuntimeException {
    public ProtocolException(String message) {
        super(message);
    }

    public ProtocolException(String message, Throwable cause) {
        super(message, cause);
    }
}
