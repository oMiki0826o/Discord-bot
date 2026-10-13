package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.Map;
import org.junit.jupiter.api.Test;

/** Verifies the Java representation follows the Python DMCC Protocol v1 envelope exactly. */
final class ProtocolEnvelopeTest {
    @Test
    void jsonRoundTripPreservesTheRequiredEnvelopeFields() {
        ProtocolEnvelope envelope = new ProtocolEnvelope(
            1, "handshake", "survival", null, Map.of("bridge_version", "0.2.3")
        );

        assertEquals(envelope, ProtocolEnvelope.fromJson(envelope.toJson()));
    }

    @Test
    void rejectsUnsupportedProtocolVersion() {
        assertThrows(ProtocolException.class, () -> ProtocolEnvelope.fromJson("""
            {"protocol_version":2,"type":"ping","server_id":"survival","request_id":null,"data":{}}
            """));
    }
}
