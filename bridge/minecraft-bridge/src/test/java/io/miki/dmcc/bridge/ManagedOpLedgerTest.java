package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Path;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class ManagedOpLedgerTest {
    private static final UUID PLAYER = UUID.fromString("123e4567-e89b-12d3-a456-426614174000");

    @TempDir Path directory;

    @Test
    void persistsOwnedOperatorIdentityAndLevelAcrossRestart() throws Exception {
        Path file = directory.resolve("managed-ops.properties");
        var first = ManagedOpLedger.load(file);
        first.put(PLAYER, "Steve", 2);
        var second = ManagedOpLedger.load(file);
        assertEquals(2, second.get(PLAYER).level());
        assertEquals("Steve", second.get(PLAYER).name());
        second.remove(PLAYER);
        assertNull(ManagedOpLedger.load(file).get(PLAYER));
    }

    @Test
    void rejectsCorruptOwnershipWithoutDeletingOriginal() throws Exception {
        Path file = directory.resolve("managed-ops.properties");
        java.nio.file.Files.writeString(file, "not-a-uuid=4:Steve\n");
        assertThrows(java.io.IOException.class, () -> ManagedOpLedger.load(file));
        assertEquals("not-a-uuid=4:Steve\n", java.nio.file.Files.readString(file));
    }

    @Test
    void enforcesValidUuidNameAndLevel() throws Exception {
        var ledger = ManagedOpLedger.load(directory.resolve("ops.properties"));
        assertThrows(IllegalArgumentException.class, () -> ledger.put(PLAYER, "Invalid Name", 2));
        assertThrows(IllegalArgumentException.class, () -> ledger.put(PLAYER, "Steve", 0));
        assertTrue(ledger.snapshot().isEmpty());
    }
}
