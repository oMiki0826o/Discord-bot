package io.miki.dmcc.bridge;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Suppress only the matching duplicate chat echo after a public command event. */
final class CommandEchoSuppressor {
    private final Map<String, Long> recent = new ConcurrentHashMap<>();

    void mark(String source, String content) {
        if (recent.size() > 512) recent.clear();
        recent.put(source + "\u0000" + content, System.nanoTime());
    }

    boolean consume(String source, String content) {
        Long time = recent.remove(source + "\u0000" + content);
        return time != null && System.nanoTime() - time < 1_000_000_000L;
    }
}
