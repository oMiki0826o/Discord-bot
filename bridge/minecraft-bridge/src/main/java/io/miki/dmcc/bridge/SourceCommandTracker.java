package io.miki.dmcc.bridge;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Correlate public player commands with their vanilla COMMAND_MESSAGE event.
 * No private command is retained or replayed.
 */
final class SourceCommandTracker {
    private record Pending(String root, String body, long createdNanos) { }
    private final Map<String, Pending> entries = new ConcurrentHashMap<>();

    void observe(String playerName, String raw) {
        if (playerName == null || raw == null || raw.length() > 1500) return;
        String command = raw.strip().replaceFirst("^/", "");
        int split = command.indexOf(' ');
        if (split < 0 || split + 1 >= command.length()) return;
        String root = command.substring(0, split).toLowerCase(java.util.Locale.ROOT);
        if (!root.equals("say") && !root.equals("me")) return;
        String body = command.substring(split + 1);
        if (body.isBlank() || body.chars().anyMatch(c -> c < 32 || c == 127)) return;
        if (entries.size() >= 512) entries.clear();
        entries.put(playerName, new Pending(root, body, System.nanoTime()));
    }

    String consume(String senderName, String content) {
        if (senderName == null || content == null) return "broadcast";
        Pending recent = entries.get(senderName);
        if (recent == null) return "broadcast";
        if (System.nanoTime() - recent.createdNanos > 2_000_000_000L) {
            entries.remove(senderName, recent);
            return "broadcast";
        }
        if (!recent.body.equals(content)) return "broadcast";
        entries.remove(senderName, recent);
        return recent.root;
    }

    void clear() {
        entries.clear();
    }
}
