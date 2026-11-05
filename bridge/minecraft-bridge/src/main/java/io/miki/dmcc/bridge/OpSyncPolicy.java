package io.miki.dmcc.bridge;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * A bounded, authenticated intent to reconcile specific linked Minecraft UUIDs.
 * This is never a blanket ops.json replacement; unknown admins are untouched.
 */
record OpSyncPolicy(List<OpSyncPolicy.Entry> entries, boolean allowRemovals) {
    record Entry(UUID playerId, String playerName, int level) { }

    static Optional<OpSyncPolicy> parse(Map<String, Object> packet) {
        if (!packet.keySet().equals(java.util.Set.of("entries", "allow_removals"))) {
            return Optional.empty();
        }
        Object rawEntries = packet.get("entries");
        Object rawRemovals = packet.get("allow_removals");
        if (!(rawEntries instanceof List<?> source) || source.isEmpty()
            || source.size() > 100 || !(rawRemovals instanceof Boolean removals)) {
            return Optional.empty();
        }
        var parsed = new ArrayList<Entry>();
        var seen = new HashSet<UUID>();
        for (Object value : source) {
            if (!(value instanceof Map<?, ?> item)
                || !item.keySet().equals(java.util.Set.of("minecraft_uuid", "minecraft_name", "level"))) {
                return Optional.empty();
            }
            Object rawId = item.get("minecraft_uuid");
            Object rawName = item.get("minecraft_name");
            Object rawLevel = item.get("level");
            if (!(rawId instanceof String id) || !(rawName instanceof String name)
                || !name.matches("[A-Za-z0-9_]{3,16}")
                || !(rawLevel instanceof Number level)
                || level.doubleValue() != level.intValue()
                || level.intValue() < (removals ? 0 : 1) || level.intValue() > 4) {
                return Optional.empty();
            }
            try {
                UUID playerId = UUID.fromString(id);
                if (!playerId.toString().equalsIgnoreCase(id) || !seen.add(playerId)) {
                    return Optional.empty();
                }
                parsed.add(new Entry(playerId, name, level.intValue()));
            } catch (IllegalArgumentException invalid) {
                return Optional.empty();
            }
        }
        return Optional.of(new OpSyncPolicy(List.copyOf(parsed), removals));
    }
}
