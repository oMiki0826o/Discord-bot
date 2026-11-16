package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

final class BridgeLocalStatsTest {
    @TempDir Path directory;
    @Test void rejectsUnsafeStatNames() {
        assertThrows(IllegalArgumentException.class, () -> BridgeLocalStats.identifier("../etc"));
        assertThrows(IllegalArgumentException.class, () -> BridgeLocalStats.identifier(""));
        assertEquals("minecraft:jump", BridgeLocalStats.identifier("jump"));
    }
    @Test void computesSavedLeaderboardAndIgnoresMalformedFiles() throws Exception {
        UUID one = UUID.fromString("123e4567-e89b-12d3-a456-426614174000");
        UUID two = UUID.fromString("223e4567-e89b-12d3-a456-426614174000");
        Files.writeString(directory.resolve(one + ".json"),
            "{\"stats\":{\"minecraft:custom\":{\"minecraft:jump\":7}}}");
        Files.writeString(directory.resolve(two + ".json"),
            "{\"stats\":{\"minecraft:custom\":{\"minecraft:jump\":11}}}");
        Files.writeString(directory.resolve("invalid.json"), "broken");
        String result = BridgeLocalStats.read(directory, Map.of(one,"Alex",two,"Steve"),"custom","jump");
        assertTrue(result.indexOf("Steve: 11") < result.indexOf("Alex: 7"));
    }
}
