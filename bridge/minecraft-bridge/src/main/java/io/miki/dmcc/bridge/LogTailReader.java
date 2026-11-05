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
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.LinkOption;
import java.util.UUID;
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
    /** Portable log cursor. Byte offsets only advance after successful delivery. */
    public record TailChunk(String content, String fileId, long nextOffset) { }

    public static TailChunk readChunk(
        Path path, long offset, String knownFileId, int maximumBytes
    ) throws IOException {
        if (maximumBytes < 1 || maximumBytes > 32_768)
            throw new IllegalArgumentException("maximumBytes out of range");
        if (offset < -1L || knownFileId == null || knownFileId.length() > 64)
            throw new IllegalArgumentException("invalid log cursor");
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("latest.log is unavailable");
        BasicFileAttributes attributes = Files.readAttributes(
            path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS
        );
        Object key = attributes.fileKey();
        String identity = (key == null ? path.toAbsolutePath().toString() : key.toString())
            + ":" + attributes.creationTime().toMillis();
        String fileId = UUID.nameUUIDFromBytes(identity.getBytes(StandardCharsets.UTF_8)).toString();
        try (FileChannel channel = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            long size = channel.size();
            if (offset == -1L) return new TailChunk("", fileId, size);
            long start = knownFileId.equals(fileId) && offset <= size ? offset : 0L;
            int count = (int) Math.min((long) maximumBytes, size - start);
            ByteBuffer buffer = ByteBuffer.allocate(count);
            channel.position(start);
            while (buffer.hasRemaining()) {
                int read = channel.read(buffer);
                if (read < 0) break;
                if (read == 0) break;
            }
            buffer.flip();
            int bytesRead = buffer.remaining();
            return new TailChunk(StandardCharsets.UTF_8.decode(buffer).toString(), fileId, start + bytesRead);
        }
    }

}
