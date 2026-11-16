package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.io.IOException;
import org.junit.jupiter.api.Test;

final class BridgeUpdateCheckerTest {
    @Test void acceptsBoundedTag() throws Exception {
        assertTrue(BridgeUpdateChecker.parseRelease("{\"tag_name\":\"v0.3.0\"}").contains("v0.3.0"));
    }
    @Test void refusesMalformedData() {
        assertThrows(IOException.class, () -> BridgeUpdateChecker.parseRelease("not json"));
        assertThrows(IOException.class, () -> BridgeUpdateChecker.parseRelease("{\"tag_name\":\"../bad\"}"));
    }
}
