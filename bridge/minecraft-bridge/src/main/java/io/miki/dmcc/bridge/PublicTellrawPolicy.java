package io.miki.dmcc.bridge;

import java.util.regex.Pattern;

/**
 * A privacy-first allowlist: only a command explicitly addressed to all
 * players is eligible for Discord forwarding. No selector filters or
 * execute-wrapped private command can match.
 */
final class PublicTellrawPolicy {
    private static final Pattern BROADCAST = Pattern.compile(
        "^/?tellraw\\s+@a\\s+\\S[\\s\\S]*$", Pattern.CASE_INSENSITIVE
    );

    private PublicTellrawPolicy() { }

    static boolean isPublicBroadcast(String input) {
        return input != null && input.length() <= 32_768 && BROADCAST.matcher(input.trim()).matches();
    }

    static String sanitize(String message) {
        if (message == null || message.isBlank()) return "";
        return message.replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]")
            .replaceAll("[\\p{Cntrl}&&[^\\n\\t]]", "")
            .substring(0, Math.min(message.length(), 1500));
    }
}
