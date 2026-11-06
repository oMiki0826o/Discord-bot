package io.miki.dmcc.bridge;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/** Validated fixed-size, server-side targeted notification from an authenticated Gateway. */
record PlayerMentionRequest(List<UUID> players, String message, String style, boolean sound) {
    boolean actionBar() {
        return style.equals("actionbar");
    }

    static Optional<PlayerMentionRequest> parse(Map<String, Object> packet) {
        if (!packet.keySet().stream().allMatch(
            key -> List.of("player_uuids", "message", "style", "sound").contains(key)
        )) return Optional.empty();
        Object playersRaw = packet.get("player_uuids");
        Object messageRaw = packet.get("message");
        Object styleRaw = packet.get("style");
        Object soundRaw = packet.getOrDefault("sound", true);
        if (!(playersRaw instanceof List<?> entries) || entries.isEmpty() || entries.size() > 16
            || !(messageRaw instanceof String message) || message.isBlank() || message.length() > 512
            || !(styleRaw instanceof String style)
            || !(style.equals("chat") || style.equals("actionbar") || style.equals("title"))
            || !(soundRaw instanceof Boolean sound)) {
            return Optional.empty();
        }
        var parsed = new ArrayList<UUID>();
        try {
            for (Object entry : entries) {
                if (!(entry instanceof String id)) return Optional.empty();
                UUID uuid = UUID.fromString(id);
                if (!uuid.toString().equalsIgnoreCase(id)) return Optional.empty();
                if (!parsed.contains(uuid)) parsed.add(uuid);
            }
        } catch (IllegalArgumentException ex) {
            return Optional.empty();
        }
        return Optional.of(new PlayerMentionRequest(List.copyOf(parsed), message, style, sound));
    }
}
