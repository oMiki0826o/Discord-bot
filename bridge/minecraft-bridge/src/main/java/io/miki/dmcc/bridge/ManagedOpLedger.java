package io.miki.dmcc.bridge;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;

/**
 * Durable ownership of only the Minecraft OP records created by the Bridge.
 * Fails closed for malformed or missing-owned-state files: it never adopts
 * preexisting manually granted operator permissions.
 */
final class ManagedOpLedger {
    record Entry(String name, int level) { }
    private static final int MAX_OWNED = 1000;
    private final Path path;
    private final Map<UUID, Entry> owned;

    private ManagedOpLedger(Path path, Map<UUID, Entry> owned) {
        this.path = path;
        this.owned = owned;
    }

    static ManagedOpLedger inMemory() {
        return new ManagedOpLedger(null, new HashMap<>());
    }

    static ManagedOpLedger load(Path file) throws IOException {
        if (file == null) throw new IllegalArgumentException("missing ledger path");
        Map<UUID, Entry> loaded = new HashMap<>();
        if (Files.exists(file)) {
            if (Files.isSymbolicLink(file) || Files.size(file) > 65_536L) {
                throw new IOException("unsafe DMCC operator ownership file");
            }
            Properties properties = new Properties();
            try (Reader reader = Files.newBufferedReader(file)) {
                properties.load(reader);
            }
            if (properties.size() > MAX_OWNED) throw new IOException("too many owned operators");
            try {
                for (String key : properties.stringPropertyNames()) {
                    UUID uuid = UUID.fromString(key);
                    if (!uuid.toString().equals(key)) throw new IllegalArgumentException("bad uuid");
                    String value = properties.getProperty(key);
                    String[] pair = value.split(":", -1);
                    if (pair.length != 2) throw new IllegalArgumentException("bad entry");
                    int level = Integer.parseInt(pair[0]);
                    validate(pair[1], level);
                    loaded.put(uuid, new Entry(pair[1], level));
                }
            } catch (IllegalArgumentException badFile) {
                throw new IOException("invalid DMCC operator ownership file", badFile);
            }
        }
        return new ManagedOpLedger(file, loaded);
    }

    Entry get(UUID uuid) {
        return owned.get(uuid);
    }

    Map<UUID, Entry> snapshot() {
        return Map.copyOf(owned);
    }

    void put(UUID uuid, String name, int level) throws IOException {
        if (uuid == null) throw new IllegalArgumentException("missing uuid");
        validate(name, level);
        Map<UUID, Entry> replacement = new HashMap<>(owned);
        replacement.put(uuid, new Entry(name, level));
        if (replacement.size() > MAX_OWNED) throw new IOException("too many owned operators");
        save(replacement);
        owned.clear();
        owned.putAll(replacement);
    }

    void remove(UUID uuid) throws IOException {
        if (!owned.containsKey(uuid)) return;
        Map<UUID, Entry> replacement = new HashMap<>(owned);
        replacement.remove(uuid);
        save(replacement);
        owned.clear();
        owned.putAll(replacement);
    }

    private static void validate(String name, int level) {
        if (name == null || !name.matches("[A-Za-z0-9_]{3,16}") || level < 1 || level > 4) {
            throw new IllegalArgumentException("invalid owned operator");
        }
    }

    private void save(Map<UUID, Entry> next) throws IOException {
        if (path == null) return;
        Path directory = path.toAbsolutePath().getParent();
        if (Files.isSymbolicLink(path)) throw new IOException("unsafe OP ledger target");
        Properties properties = new Properties();
        next.forEach((uuid, entry) ->
            properties.setProperty(uuid.toString(), entry.level() + ":" + entry.name())
        );
        Path temporary = Files.createTempFile(directory, ".dmcc-ops-", ".tmp");
        try {
            try (Writer writer = Files.newBufferedWriter(temporary)) {
                properties.store(writer, "DMCC-managed Minecraft operators");
            }
            try {
                Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException unsupported) {
                Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING);
            }
        } finally {
            Files.deleteIfExists(temporary);
        }
    }
}
