package io.miki.dmcc.bridge;

import java.util.Locale;

/**
 * Deliberate public-only command filter; never forward private or
 * authentication commands through Discord, even with command relay enabled.
 */
final class PublicPlayerCommandPolicy {
    private PublicPlayerCommandPolicy() { }

    static String sanitize(String raw) {
        if (raw == null || raw.isBlank() || raw.length() > 1500
            || raw.chars().anyMatch(c -> c < 32 || c == 127)) return "";
        String command = raw.strip();
        if (command.startsWith("/")) command = command.substring(1);
        int whitespace = command.indexOf(' ');
        String root = (whitespace < 0 ? command : command.substring(0, whitespace))
            .toLowerCase(Locale.ROOT);
        boolean publicMessage = (root.equals("say") || root.equals("me"))
            && whitespace >= 0 && !command.substring(whitespace).isBlank();
        boolean allPlayers = root.equals("tellraw")
            && PublicTellrawPolicy.isPublicBroadcast(command);
        if (!publicMessage && !allPlayers && !(root.equals("list") && whitespace < 0)) {
            return "";
        }
        return "/" + command.replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]");
    }
}
