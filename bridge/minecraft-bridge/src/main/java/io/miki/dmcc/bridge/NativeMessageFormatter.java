package io.miki.dmcc.bridge;

import net.minecraft.network.chat.Component;

/**
 * Bounded presentation of source messages when optional signed-chat replacement
 * is explicitly enabled. Never constructs external click actions.
 */
final class NativeMessageFormatter {
    private NativeMessageFormatter() { }

    static Component playerChat(String sender, String message) {
        return format("<" + sanitize(sender, 48) + "> ", message);
    }

    static Component publicCommand(String sender, String message) {
        return format("[" + sanitize(sender, 48) + "] ", message);
    }

    private static Component format(String prefix, String message) {
        String content = sanitize(message, 1500);
        String merged = prefix + content;
        if (merged.length() > 1500) merged = merged.substring(0, 1500);
        return Component.literal(merged);
    }

    private static String sanitize(String raw, int limit) {
        if (raw == null) return "";
        String safe = raw.replaceAll("[\\p{Cntrl}]", " ")
            .replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]");
        return safe.length() <= limit ? safe : safe.substring(0, limit);
    }
}
