package io.miki.dmcc.bridge;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Safe style-only Minecraft component construction, without interactive events or commands. */
final class RichTextComponents {
    private static final Set<String> FIELDS = Set.of(
        "text", "bold", "italic", "underlined", "strikethrough", "color"
    );

    private RichTextComponents() { }

    static Optional<Component> parse(Map<String, Object> packet) {
        Object raw = packet.get("segments");
        if (!(raw instanceof List<?> segments) || segments.isEmpty() || segments.size() > 128) {
            return Optional.empty();
        }
        MutableComponent output = Component.empty();
        int length = 0;
        for (Object value : segments) {
            if (!(value instanceof Map<?, ?> entry) || !FIELDS.containsAll(entry.keySet())) {
                return Optional.empty();
            }
            Object textRaw = entry.get("text");
            if (!(textRaw instanceof String text) || text.isEmpty() || text.length() > 1800) {
                return Optional.empty();
            }
            length += text.length();
            if (length > 1800) return Optional.empty();
            for (String flag : List.of("bold", "italic", "underlined", "strikethrough")) {
                Object item = entry.get(flag);
                if (item != null && !(item instanceof Boolean)) return Optional.empty();
            }
            Object colorRaw = entry.getOrDefault("color", "white");
            if (!(colorRaw instanceof String color) || !(color.equals("white") || color.equals("gray"))) {
                return Optional.empty();
            }
            MutableComponent fragment = Component.literal(text);
            fragment.withStyle(style -> style
                .withBold(Boolean.TRUE.equals(entry.get("bold")))
                .withItalic(Boolean.TRUE.equals(entry.get("italic")))
                .withUnderlined(Boolean.TRUE.equals(entry.get("underlined")))
                .withStrikethrough(Boolean.TRUE.equals(entry.get("strikethrough")))
                .withColor(color.equals("gray") ? ChatFormatting.GRAY : ChatFormatting.WHITE)
            );
            output.append(fragment);
        }
        return Optional.of(output);
    }
}
