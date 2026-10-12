package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.io.StringReader;
import org.junit.jupiter.api.Test;

/** Defines the local Bridge-to-Bot configuration contract before network code is added. */
final class BridgeSettingsTest {
    @Test
    void parsesACompleteGatewayConfiguration() throws Exception {
        BridgeSettings settings = BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            """));

        assertEquals("survival", settings.serverId());
        assertEquals("127.0.0.1", settings.gatewayHost());
        assertEquals(8765, settings.gatewayPort());
        assertEquals("shared-secret", settings.authenticationSecret());
    }

    @Test
    void rejectsUnsafeOrIncompleteConfiguration() {
        assertThrows(ProtocolException.class, () -> BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=example.com
            gateway_port=8765
            authentication_secret=
            """)));
    }
}
