package io.miki.dmcc.bridge;

import java.util.regex.Pattern;

/**
 * A privacy-first allowlist: only a command explicitly addressed to all
 * players is eligible for Discord forwarding. No selector filters or
 * execute-wrapped private command can match.
 */
public final class PublicTellrawPolicy {
    private static final Pattern BROADCAST = Pattern.compile(
        "^/?tellraw\\s+@a\\s+\\S[\\s\\S]*$", Pattern.CASE_INSENSITIVE
    );

    private PublicTellrawPolicy() { }

    static boolean isPublicBroadcast(String input) {
        return input != null && input.length() <= 32_768 && BROADCAST.matcher(input.trim()).matches();
    }

    public static java.util.Optional<String> consensus(java.util.List<String> rendered) {
        if (rendered == null || rendered.isEmpty() || rendered.size() > 64) {
            return java.util.Optional.empty();
        }
        String first = rendered.getFirst();
        if (first == null || first.isBlank() || first.length() > 1500) {
            return java.util.Optional.empty();
        }
        for (String candidate : rendered) {
            if (!first.equals(candidate)) return java.util.Optional.empty();
        }
        return java.util.Optional.of(first);
    }

    static String sanitize(String message) {
        if (message == null || message.isBlank()) return "";
        String sanitized = message.replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]")
            .replaceAll("[\\p{Cntrl}&&[^\\n\\t]]", "");
        return sanitized.substring(0, Math.min(sanitized.length(), 1500));
    }
}
