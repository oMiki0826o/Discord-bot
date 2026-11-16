package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.StringReader;
import org.junit.jupiter.api.Test;

/** Contract for safe DMCC live configuration reload routing. */
final class BridgeReloadPlanTest {
    private static final String BASE = """
        server_id=survival
        gateway_host=127.0.0.1
        gateway_port=8765
        authentication_secret=test-secret
        """;

    private static BridgeSettings read(String config) throws Exception {
        return BridgeSettings.fromReader(new StringReader(config));
    }

    @Test
    void presentationAndLinkOptionsDoNotReconnect() throws Exception {
        BridgeSettings base = read(BASE);
        assertFalse(BridgeReloadPlan.requiresReconnect(base, read(BASE + """
            translation_locale=zh_tw
            overwrite_native_messages=true
            require_linking=true
            unlinked_player_action=freeze
            op_sync_enabled=true
            pending_request_ttl_millis=30000
            """)));
    }

    @Test
    void IdentityCredentialsAndSocketSettingsRequireReconnect() throws Exception {
        BridgeSettings base = read(BASE);
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE.replace("server_id=survival", "server_id=creative"))));
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE.replace("test-secret", "new-secret"))));
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE.replace("gateway_port=8765", "gateway_port=9876"))));
        assertTrue(BridgeReloadPlan.requiresReconnect(base,
            read(BASE + "read_timeout_millis=90000\n")));
    }
}
