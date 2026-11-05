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
    void cursorStartsAtEndAndResumesWithoutDuplicateHistory() throws Exception {
        Path log = directory.resolve("latest.log");
        Files.writeString(log, "older history\n", StandardCharsets.UTF_8);
        var initial = LogTailReader.readChunk(log, -1L, "", 8192);
        assertEquals("", initial.content());
        assertTrue(initial.nextOffset() > 0);
        assertTrue(!initial.fileId().isEmpty());
        Files.writeString(log, "new line\n", StandardCharsets.UTF_8, java.nio.file.StandardOpenOption.APPEND);
        var next = LogTailReader.readChunk(log, initial.nextOffset(), initial.fileId(), 8192);
        assertEquals("new line\n", next.content());
        assertEquals(Files.size(log), next.nextOffset());
        var again = LogTailReader.readChunk(log, next.nextOffset(), next.fileId(), 8192);
        assertEquals("", again.content());
    }

    @Test
    void cursorDetectsRotationAndSupportsBoundedBacklog() throws Exception {
        Path log = directory.resolve("latest.log");
        Files.writeString(log, "old content\n", StandardCharsets.UTF_8);
        var original = LogTailReader.readChunk(log, -1L, "", 8192);
        Path rotated = directory.resolve("latest.log.1");
        Files.move(log, rotated);
        Files.writeString(log, "abc\n123\n", StandardCharsets.UTF_8);
        var first = LogTailReader.readChunk(log, original.nextOffset(), original.fileId(), 4);
        assertEquals("abc\n", first.content());
        assertTrue(!original.fileId().equals(first.fileId()));
        assertEquals(4L, first.nextOffset());
        var second = LogTailReader.readChunk(log, first.nextOffset(), first.fileId(), 4);
        assertEquals("123\n", second.content());
    }

    @Test
    void missingFileReturnsEmptyTail() throws Exception {
        assertEquals("", LogTailReader.read(directory.resolve("missing.log"), 64));
    }
}
