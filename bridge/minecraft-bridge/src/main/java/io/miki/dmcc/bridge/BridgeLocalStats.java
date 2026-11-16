package io.miki.dmcc.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

/** Bounded per-player leaderboard read; call only from a background worker. */
final class BridgeLocalStats {
    private BridgeLocalStats() { }

    static String identifier(String raw) {
        if (raw == null || !raw.matches("[a-z0-9_.:-]{1,96}")) {
            throw new IllegalArgumentException("Invalid statistic identifier");
        }
        return raw.contains(":") ? raw : "minecraft:" + raw;
    }

    static String read(Path directory, Map<UUID, String> names, String requestedType, String requestedStat)
        throws IOException {
        String type = identifier(requestedType);
        String stat = identifier(requestedStat);
        if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)) {
            return "No saved statistics are available.";
        }
        List<StatRow> rows = new ArrayList<>();
        try (Stream<Path> stream = Files.list(directory)) {
            List<Path> files = stream.filter(path -> Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))
                .filter(path -> path.getFileName().toString().endsWith(".json"))
                .sorted().limit(2048).toList();
            for (Path file : files) {
                String filename = file.getFileName().toString();
                UUID id;
                try { id = UUID.fromString(filename.substring(0, filename.length() - 5)); }
                catch (IllegalArgumentException invalid) { continue; }
                try {
                    if (Files.size(file) > 1_048_576) continue;
                    JsonObject root = JsonParser.parseString(Files.readString(file)).getAsJsonObject();
                    JsonObject values = root.getAsJsonObject("stats");
                    if (values == null) continue;
                    JsonObject category = values.getAsJsonObject(type);
                    if (category == null) continue;
                    JsonElement value = category.get(stat);
                    if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) continue;
                    int score = value.getAsInt();
                    if (score <= 0) continue;
                    rows.add(new StatRow(names.getOrDefault(id, id.toString()), score));
                } catch (IOException | RuntimeException ignored) {
                    // Invalid individual player stats must not abort other player results.
                }
            }
        }
        rows.sort(Comparator.comparingInt(StatRow::value).reversed().thenComparing(StatRow::name));
        if (rows.isEmpty()) return "No results for " + type + " / " + stat + ".";
        StringBuilder output = new StringBuilder("Stats ").append(type).append(" / ").append(stat).append(':');
        for (int i = 0; i < Math.min(10, rows.size()); i++) {
            StatRow row = rows.get(i);
            output.append("\n").append(i + 1).append(". ").append(row.name()).append(": ").append(row.value());
        }
        return output.toString();
    }

    private record StatRow(String name, int value) { }
}
