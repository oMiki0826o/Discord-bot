/*
 * test_mod/minecraft-bridge/src/test/java/io/miki/dmcc/bridge/FrameCodecTest.java
 *
 * Verifies the Java side of the DMCC Protocol v1 length-prefixed frame boundary.
 */
package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

final class FrameCodecTest {
    @Test
    void roundTripPreservesUtf8JsonPayload() {
        byte[] payload = "{\"type\":\"ping\",\"message\":\"流螢\"}"
            .getBytes(StandardCharsets.UTF_8);

        byte[] frame = FrameCodec.encode(payload, 1024);

        assertArrayEquals(payload, FrameCodec.decode(frame, 1024));
    }

    @Test
    void rejectsDeclaredLengthAboveConfiguredLimit() {
        byte[] oversized = new byte[] {0, 0, 4, 1};

        assertThrows(ProtocolException.class, () -> FrameCodec.decode(oversized, 1024));
    }
}
