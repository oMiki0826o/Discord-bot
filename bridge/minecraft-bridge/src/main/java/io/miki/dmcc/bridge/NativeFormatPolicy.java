package io.miki.dmcc.bridge;

import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

/**
 * Native Minecraft-to-Minecraft preview formatting configuration.
 * Parsing settings remain independent from network authentication and OP policy.
 */
record NativeFormatPolicy(
    boolean markdown,
    boolean hyperlinks,
    boolean timestamps,
    boolean unicodeEmojis,
    boolean customEmojis,
    boolean mentions,
    boolean echoPlayerCommands,
    boolean echoGameMode,
    Map<String, String> emojiAliases
) {
    static NativeFormatPolicy defaults() {
        return new NativeFormatPolicy(true, true, true, true, true, true, false, false, Map.of());
    }

    static NativeFormatPolicy load(Path file) throws IOException {
        Properties properties = new Properties();
        try (Reader reader = Files.newBufferedReader(file)) {
            properties.load(reader);
        }
        Map<String, String> aliases = new HashMap<>();
        for (String key : properties.stringPropertyNames()) {
            if (!key.startsWith("emoji.")) continue;
            String alias = key.substring(6);
            String glyph = properties.getProperty(key);
            if (alias.matches("[A-Za-z0-9_]{1,32}") && glyph != null
                && !glyph.isBlank() && glyph.length() <= 16 && aliases.size() < 256) {
                aliases.put(alias.toLowerCase(java.util.Locale.ROOT), glyph);
            }
        }
        return new NativeFormatPolicy(
            flag(properties, "native_markdown"),
            flag(properties, "native_hyperlinks"),
            flag(properties, "native_timestamps"),
            flag(properties, "native_unicode_emojis"),
            flag(properties, "native_custom_emojis"),
            flag(properties, "native_mentions"),
            "true".equals(properties.getProperty("echo_player_command_to_source", "false")),
            "true".equals(properties.getProperty("echo_player_game_mode_to_source", "false")),
            Map.copyOf(aliases)
        );
    }

    private static boolean flag(Properties properties, String name) {
        String value = properties.getProperty(name, "true").trim();
        if ("true".equals(value)) return true;
        if ("false".equals(value)) return false;
        throw new ProtocolException(name + " must be true or false");
    }
}
