/*
 * Reads a bounded UTF-8 tail from a Minecraft log without loading the full
 * file into memory. Disk I/O belongs on the Bridge background worker.
 */
package io.miki.dmcc.bridge;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;

/** Bounded latest.log tail reader. */
public final class LogTailReader {
    private LogTailReader() { }

    public static String read(Path path, int maximumBytes) throws IOException {
        if (maximumBytes < 1) throw new IllegalArgumentException("maximumBytes must be positive");
        if (!Files.isRegularFile(path)) return "";
        try (FileChannel channel = FileChannel.open(path, StandardOpenOption.READ)) {
            long size = channel.size();
            int count = (int) Math.min(size, maximumBytes);
            ByteBuffer buffer = ByteBuffer.allocate(count);
            channel.position(Math.max(0, size - count));
            while (buffer.hasRemaining() && channel.read(buffer) >= 0) { }
            buffer.flip();
            return StandardCharsets.UTF_8.decode(buffer).toString();
        }
    }
}
