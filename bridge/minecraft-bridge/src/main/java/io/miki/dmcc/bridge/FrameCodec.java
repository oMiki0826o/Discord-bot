/*
 * Encodes and validates the unsigned 32-bit big-endian length prefix used by
 * DMCC Protocol v1.  JSON interpretation belongs to a higher protocol layer.
 */
package io.miki.dmcc.bridge;

import java.nio.ByteBuffer;

public final class FrameCodec {
    private static final int HEADER_BYTES = Integer.BYTES;

    private FrameCodec() {
    }

    public static byte[] encode(byte[] payload, int maximumPayloadBytes) {
        validateMaximum(maximumPayloadBytes);
        if (payload == null) {
            throw new ProtocolException("payload must not be null");
        }
        if (payload.length > maximumPayloadBytes) {
            throw new ProtocolException("payload exceeds configured limit");
        }
        return ByteBuffer.allocate(HEADER_BYTES + payload.length)
            .putInt(payload.length)
            .put(payload)
            .array();
    }

    public static byte[] decode(byte[] frame, int maximumPayloadBytes) {
        validateMaximum(maximumPayloadBytes);
        if (frame == null || frame.length < HEADER_BYTES) {
            throw new ProtocolException("frame is shorter than its header");
        }
        ByteBuffer buffer = ByteBuffer.wrap(frame);
        int declaredLength = buffer.getInt();
        if (declaredLength < 0 || declaredLength > maximumPayloadBytes) {
            throw new ProtocolException("declared payload exceeds configured limit");
        }
        if (frame.length != HEADER_BYTES + declaredLength) {
            throw new ProtocolException("frame length does not match header");
        }
        byte[] payload = new byte[declaredLength];
        buffer.get(payload);
        return payload;
    }

    private static void validateMaximum(int maximumPayloadBytes) {
        if (maximumPayloadBytes <= 0) {
            throw new IllegalArgumentException("maximumPayloadBytes must be positive");
        }
    }
}
