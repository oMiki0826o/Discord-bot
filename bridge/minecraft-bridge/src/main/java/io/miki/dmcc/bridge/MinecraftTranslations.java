package io.miki.dmcc.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.contents.TranslatableContents;
import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.List;
import java.util.stream.Stream;
import java.util.regex.Pattern;

/**
 * Immutable language snapshot for Minecraft's translatable message components.
 *
 * Loads bounded server-local assets rather than downloading language packs on the
 * server tick. Missing files or keys always fall back to English or the key.
 */
final class MinecraftTranslations {
    private static final Pattern LOCALE = Pattern.compile("[a-z]{2}_[a-z]{2}");
    private static final int MAX_TEXT = 1800;
    private static final int MAX_ENTRIES = 50_000;
    private static final long MAX_FILE_BYTES = 4_000_000L;
    private final Map<String, String> values;

    private MinecraftTranslations(Map<String, String> values) {
        this.values = Collections.unmodifiableMap(new HashMap<>(values));
    }

    static MinecraftTranslations empty() {
        return new MinecraftTranslations(Map.of());
    }

    static MinecraftTranslations load(Path directory, String rawLocale) throws IOException {
        return load(directory, rawLocale, List.of());
    }

    static MinecraftTranslations load(Path directory, String rawLocale, Iterable<Path> roots) throws IOException {
        return load(directory, rawLocale, roots, null);
    }

    static MinecraftTranslations load(
        Path directory, String rawLocale, Iterable<Path> roots, String minecraftVersion
    ) throws IOException {
        return load(directory, rawLocale, roots, minecraftVersion,
            MinecraftPackTranslations.Snapshot.empty());
    }

    static MinecraftTranslations load(
        Path directory, String rawLocale, Iterable<Path> roots, String minecraftVersion,
        MinecraftPackTranslations.Snapshot packs
    ) throws IOException {
        if (directory == null) throw new IllegalArgumentException("missing language directory");
        String locale = rawLocale == null ? "en_us" : rawLocale.toLowerCase(Locale.ROOT);
        if (!LOCALE.matcher(locale).matches()) throw new IllegalArgumentException("invalid locale");
        if (minecraftVersion != null && !minecraftVersion.matches("[0-9]{1,3}\\.[0-9]{1,3}(\\.[0-9]{1,3})?")) {
            throw new IllegalArgumentException("invalid Minecraft version for cached language");
        }
        Map<String, String> result = new HashMap<>();
        readLanguage(directory.resolve(locale + ".json"), result);
        readModRoots(roots, locale, result);
        if (packs != null) packs.target().forEach(result::putIfAbsent);
        if (minecraftVersion != null) {
            readLanguage(directory.resolve("mojang").resolve(minecraftVersion).resolve(locale + ".json"), result);
        }
        if (!locale.equals("en_us")) {
            readLanguage(directory.resolve("en_us.json"), result);
            readModRoots(roots, "en_us", result);
            if (packs != null) packs.english().forEach(result::putIfAbsent);
            if (minecraftVersion != null) {
                readLanguage(directory.resolve("mojang").resolve(minecraftVersion).resolve("en_us.json"), result);
            }
        }
        return new MinecraftTranslations(result);
    }

    private static void readModRoots(
        Iterable<Path> roots, String locale, Map<String, String> target
    ) {
        if (roots == null) return;
        int scanned = 0;
        for (Path root : roots) {
            if (++scanned > 256) break;
            if (root == null) continue;
            Path assets = root.resolve("assets");
            if (!Files.isDirectory(assets) || Files.isSymbolicLink(assets)) continue;
            try (Stream<Path> namespaces = Files.list(assets)) {
                for (Path namespace : namespaces.limit(128).toList()) {
                    if (!Files.isDirectory(namespace) || Files.isSymbolicLink(namespace)) continue;
                    try {
                        readLanguage(namespace.resolve("lang").resolve(locale + ".json"), target);
                    } catch (IOException invalid) {
                        // One damaged or oversized mod translation must not break other mods.
                    }
                }
            } catch (IOException invalid) {
                // Optional mod resource roots may be missing or temporarily inaccessible.
            }
        }
    }

    private static void readLanguage(Path file, Map<String, String> target) throws IOException {
        if (!Files.isRegularFile(file) || Files.isSymbolicLink(file)) return;
        if (Files.size(file) > MAX_FILE_BYTES) {
            throw new IOException("Minecraft language file exceeds size limit");
        }
        try (Reader input = Files.newBufferedReader(file)) {
            JsonElement raw = JsonParser.parseReader(input);
            if (!raw.isJsonObject()) return;
            JsonObject object = raw.getAsJsonObject();
            if (object.size() > MAX_ENTRIES) {
                throw new IOException("too many Minecraft translations");
            }
            for (Map.Entry<String, JsonElement> item : object.entrySet()) {
                JsonElement element = item.getValue();
                if (item.getKey().length() > 256 || !element.isJsonPrimitive()
                    || !element.getAsJsonPrimitive().isString()) continue;
                String value = element.getAsString();
                if (value.length() <= 2048) {
                    target.putIfAbsent(item.getKey(), value);
                }
            }
        } catch (RuntimeException invalid) {
            // Corrupted optional locale files must not prevent server startup.
        }
    }

    String translateKey(String key, Object... args) {
        if (key == null || key.isBlank()) return "";
        String format = values.getOrDefault(key, key);
        if (args == null || args.length == 0) return limit(format);
        StringBuilder output = new StringBuilder();
        int nextArgument = 0;
        for (int i = 0; i < format.length() && output.length() < MAX_TEXT;) {
            char ch = format.charAt(i);
            if (ch != '%' || i + 1 >= format.length()) {
                output.append(ch);
                i++;
                continue;
            }
            char candidate = format.charAt(i + 1);
            if (candidate == '%') {
                output.append('%');
                i += 2;
                continue;
            }
            int end = i + 1;
            while (end < format.length() && Character.isDigit(format.charAt(end))
                && end - i <= 4) end++;
            int index;
            if (end > i + 1 && end + 1 < format.length()
                && format.charAt(end) == '$' && format.charAt(end + 1) == 's') {
                try {
                    index = Integer.parseInt(format.substring(i + 1, end)) - 1;
                } catch (NumberFormatException invalid) {
                    index = -1;
                }
                if (index >= 0 && index < args.length) {
                    output.append(args[index]);
                } else {
                    output.append(format, i, end + 2);
                }
                i = end + 2;
            } else if (candidate == 's') {
                if (nextArgument < args.length) {
                    output.append(args[nextArgument++]);
                } else {
                    output.append("%s");
                }
                i += 2;
            } else {
                output.append('%');
                i++;
            }
        }
        return limit(output.toString());
    }

    String translate(Component component) {
        return translate(component, 0);
    }

    private String translate(Component component, int depth) {
        if (component == null) return "";
        if (depth > 12) return limit(component.getString());
        if (!(component.getContents() instanceof TranslatableContents part)) {
            return limit(component.getString());
        }
        Object[] original = part.getArgs();
        Object[] translated = new Object[original.length];
        for (int i = 0; i < original.length; i++) {
            Object value = original[i];
            translated[i] = value instanceof Component nested
                ? translate(nested, depth + 1) : value;
        }
        StringBuilder result = new StringBuilder(translateKey(part.getKey(), translated));
        for (Component sibling : component.getSiblings()) {
            if (result.length() >= MAX_TEXT) break;
            result.append(translate(sibling, depth + 1));
        }
        return limit(result.toString());
    }

    private static String limit(String value) {
        return value.length() <= MAX_TEXT ? value : value.substring(0, MAX_TEXT);
    }
}
