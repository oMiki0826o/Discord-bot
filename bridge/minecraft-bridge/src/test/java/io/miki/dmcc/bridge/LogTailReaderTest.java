package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** Verifies bounded tail reads and UTF-8 boundary handling. */
final class LogTailReaderTest {
    @TempDir Path directory;

    @Test
    void readsOnlyTheBoundedFileTail() throws Exception {
        Path log = directory.resolve("latest.log");
        Files.writeString(log, "prefix-" + "x".repeat(1_000) + "-ending", StandardCharsets.UTF_8);
        String tail = LogTailReader.read(log, 32);
        assertTrue(tail.endsWith("-ending"));
        assertTrue(tail.getBytes(StandardCharsets.UTF_8).length <= 34);
    }

    @Test
    void returnsValidTextWhenTailStartsInsideUtf8Character() throws Exception {
        Path log = directory.resolve("latest.log");
        Files.writeString(log, "前綴" + "測".repeat(20) + "結尾", StandardCharsets.UTF_8);
        String tail = LogTailReader.read(log, 17);
        assertTrue(tail.endsWith("結尾"));
        assertTrue(StandardCharsets.UTF_8.newEncoder().canEncode(tail));
    }

    @Test
    void missingFileReturnsEmptyTail() throws Exception {
        assertEquals("", LogTailReader.read(directory.resolve("missing.log"), 64));
    }
}
