package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class OpSyncPolicyTest {
    private static final String UUID_ONE = "123e4567-e89b-12d3-a456-426614174000";

    @Test
    void parsesBoundedGrantOnlyLinkedPlayerPolicy() {
        var packet = Map.<String, Object>of(
            "entries", List.of(Map.of(
                "minecraft_uuid", UUID_ONE, "minecraft_name", "Steve", "level", 2
            )),
            "allow_removals", false
        );
        var policy = OpSyncPolicy.parse(packet);
        assertTrue(policy.isPresent());
        assertEquals(1, policy.get().entries().size());
        assertEquals(2, policy.get().entries().getFirst().level());
        assertFalse(policy.get().allowRemovals());
    }

    @Test
    void rejectsDangerousUnvalidatedOpPayloads() {
        assertTrue(OpSyncPolicy.parse(Map.of(
            "entries", List.of(Map.of(
                "minecraft_uuid", UUID_ONE, "minecraft_name", "Steve", "level", 5
            )), "allow_removals", false
        )).isEmpty());
        assertTrue(OpSyncPolicy.parse(Map.of(
            "entries", List.of(Map.of(
                "minecraft_uuid", UUID_ONE, "minecraft_name", "Steve", "level", 0
            )), "allow_removals", false
        )).isEmpty());
        assertTrue(OpSyncPolicy.parse(Map.of(
            "entries", List.of(Map.of(
                "minecraft_uuid", UUID_ONE, "minecraft_name", "Steve", "level", 4
            )), "allow_removals", "yes"
        )).isEmpty());
        assertTrue(OpSyncPolicy.parse(Map.of(
            "entries", List.of(Map.of(
                "minecraft_uuid", "invalid", "minecraft_name", "Steve", "level", 4
            )), "allow_removals", false
        )).isEmpty());
    }

    @Test
    void duplicateUuidsAreRejected() {
        var entry = Map.of(
            "minecraft_uuid", UUID_ONE, "minecraft_name", "Steve", "level", 2
        );
        assertTrue(OpSyncPolicy.parse(Map.of(
            "entries", List.of(entry, entry), "allow_removals", false
        )).isEmpty());
    }
}
