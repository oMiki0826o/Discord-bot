package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/** Verifies that the staged output has the Fabric metadata required for a loadable mod JAR. */
class BridgeMetadataTest {
    @Test
    void fabricMetadataDeclaresTheBridgeEntrypoint() throws Exception {
        try (InputStream stream = getClass().getClassLoader().getResourceAsStream("fabric.mod.json")) {
            String metadata = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            assertTrue(metadata.contains("minecraft_bridge"));
            assertTrue(metadata.contains("io.miki.dmcc.bridge.BridgeMod"));
        }
    }
}
