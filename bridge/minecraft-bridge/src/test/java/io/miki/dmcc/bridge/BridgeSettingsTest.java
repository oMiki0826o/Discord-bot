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
        assertEquals(1_500, settings.gracefulShutdownTimeoutMillis());
    }

    @Test
    void operatorSynchronizationRequiresExplicitServerOptIn() throws Exception {
        var defaultConfig = BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            """));
        assertFalse(defaultConfig.opSyncEnabled());
        var optIn = BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            op_sync_enabled=true
            """));
        assertTrue(optIn.opSyncEnabled());
        assertThrows(ProtocolException.class, () -> BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            op_sync_enabled=maybe
            """)));
    }

    @Test
    void disabledLinkGateIsBackwardCompatible() throws Exception {
        var settings = BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            """));
        assertEquals(false, settings.requireLinking());
        assertEquals("kick", settings.unlinkedPlayerAction());
    }

    @Test
    void acceptsExplicitlyEnabledKickOrFreezeGate() throws Exception {
        for (String action : new String[]{"kick", "freeze"}) {
            var settings = BridgeSettings.fromReader(new StringReader(
                "server_id=survival\n" +
                "gateway_host=127.0.0.1\n" +
                "gateway_port=8765\n" +
                "authentication_secret=shared-secret\n" +
                "require_linking=true\n" +
                "unlinked_player_action=" + action + "\n"
            ));
            assertEquals(true, settings.requireLinking());
            assertEquals(action, settings.unlinkedPlayerAction());
        }
    }

    @Test
    void invalidLinkGateSettingsFailBeforeServerStarts() {
        assertThrows(ProtocolException.class, () -> BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            require_linking=TRUEISH
            """)));
        assertThrows(ProtocolException.class, () -> BridgeSettings.fromReader(new StringReader("""
            server_id=survival
            gateway_host=127.0.0.1
            gateway_port=8765
            authentication_secret=shared-secret
            require_linking=true
            unlinked_player_action=op
            """)));
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
