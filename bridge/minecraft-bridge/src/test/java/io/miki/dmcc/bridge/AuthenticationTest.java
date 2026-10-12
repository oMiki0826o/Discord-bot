package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Verifies Java calculates the HMAC-SHA256 response expected by the Python Gateway. */
final class AuthenticationTest {
    @Test
    void producesStableHmacSha256Response() {
        assertEquals(
            "a1e505e96c6aa1ece082bb9efb06c80f12913d217a7ac2b08b347630787d1da0",
            Authentication.createResponse("challenge", "secret")
        );
    }
}
