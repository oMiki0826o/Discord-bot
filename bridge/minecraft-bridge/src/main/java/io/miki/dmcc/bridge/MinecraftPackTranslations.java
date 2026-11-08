package io.miki.dmcc.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.packs.PackType;
import net.minecraft.server.packs.resources.IoSupplier;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/**
 * Snapshot CLIENT_RESOURCES translations from the server's selected packs,
 * not indiscriminately from disabled packs on disk.
 *
 * Called on the server lifecycle/reload thread only; results are immutable.
 */
final class MinecraftPackTranslations {
    record Snapshot(Map<String, String> target, Map<String, String> english) {
        static Snapshot empty() { return new Snapshot(Map.of(), Map.of()); }
    }

    private MinecraftPackTranslations() { }

    static Snapshot snapshot(MinecraftServer server, String locale) {
        if (server == null || locale == null || !locale.matches("[a-z]{2}_[a-z]{2}")) {
            return Snapshot.empty();
        }
        Map<String, String> target = new HashMap<>();
        Map<String, String> english = new HashMap<>();
        try {
            int scanned = 0;
            for (var pack : server.getPackRepository().getSelectedPacks()) {
                if (++scanned > 128) break;
                try {
                    pack.open().forEach(resource -> {
                        try (resource) {
                            Set<String> namespaces = resource.getNamespaces(PackType.CLIENT_RESOURCES);
                            int namespaceCount = 0;
                            for (String namespace : namespaces) {
                                if (++namespaceCount > 128) break;
                                read(resource, namespace, locale, target);
                                if (!locale.equals("en_us")) {
                                    read(resource, namespace, "en_us", english);
                                }
                            }
                        } catch (Exception ignored) {
                            // A single unreadable selected pack cannot halt server start.
                        }
                    });
                } catch (RuntimeException ignored) {
                    // Safely skip a disabled/corrupted resource pack.
                }
            }
        } catch (RuntimeException ignored) {
            // No active pack repository yet; the next reload will refresh.
        }
        return new Snapshot(Map.copyOf(target), Map.copyOf(english));
    }

    private static void read(
        net.minecraft.server.packs.PackResources resource,
        String namespace, String locale, Map<String, String> output
    ) {
        if (output.size() >= 50_000) return;
        try {
            ResourceLocation id = ResourceLocation.fromNamespaceAndPath(
                namespace, "lang/" + locale + ".json"
            );
            IoSupplier<InputStream> input = resource.getResource(PackType.CLIENT_RESOURCES, id);
            if (input == null) return;
            try (InputStream stream = input.get()) {
                byte[] bytes = stream.readNBytes(4_000_001);
                if (bytes.length > 4_000_000) return;
                JsonElement tree = JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8));
                if (!tree.isJsonObject()) return;
                JsonObject object = tree.getAsJsonObject();
                for (Map.Entry<String, JsonElement> item : object.entrySet()) {
                    JsonElement value = item.getValue();
                    if (output.size() >= 50_000) break;
                    if (item.getKey().length() > 256 || !value.isJsonPrimitive()
                        || !value.getAsJsonPrimitive().isString()) continue;
                    String translated = value.getAsString();
                    if (translated.length() <= 2048) output.putIfAbsent(item.getKey(), translated);
                }
            }
        } catch (IOException | RuntimeException ignored) {
            // Resource packs can disappear or be replaced during reload.
        }
    }
}
