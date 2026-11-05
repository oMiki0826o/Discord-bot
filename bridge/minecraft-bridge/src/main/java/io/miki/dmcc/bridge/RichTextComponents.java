package io.miki.dmcc.bridge;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.HoverEvent;
import java.net.URI;
import java.util.Locale;
import net.minecraft.network.chat.TextColor;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Safe style-only Minecraft component construction, without interactive events or commands. */
final class RichTextComponents {
    private static final Set<String> FIELDS = Set.of(
        "text", "bold", "italic", "underlined", "strikethrough", "obfuscated", "color",
        "click_url", "hover_text"
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
            for (String flag : List.of("bold", "italic", "underlined", "strikethrough", "obfuscated")) {
                Object item = entry.get(flag);
                if (item != null && !(item instanceof Boolean)) return Optional.empty();
            }
            Object colorRaw = entry.containsKey("color") ? entry.get("color") : "white";
            if (!(colorRaw instanceof String color)
                || !(color.equals("white") || color.equals("gray") || color.matches("#[0-9a-fA-F]{6}"))) {
                return Optional.empty();
            }
            URI click = null;
            if (entry.containsKey("click_url")) {
                Object rawUrl = entry.get("click_url");
                if (!(rawUrl instanceof String url)) return Optional.empty();
                click = safeUrl(url);
                if (click == null) return Optional.empty();
            }
            Object rawHover = entry.get("hover_text");
            if (rawHover != null && (!(rawHover instanceof String hover)
                || hover.length() > 512 || hover.chars().anyMatch(c -> c < 32 || c == 127))) {
                return Optional.empty();
            }
            URI clickTarget = click;
            String hoverLabel = rawHover instanceof String value ? value : null;
            MutableComponent fragment = Component.literal(text);
            fragment.withStyle(style -> {
                var styled = style
                .withBold(Boolean.TRUE.equals(entry.get("bold")))
                .withItalic(Boolean.TRUE.equals(entry.get("italic")))
                .withUnderlined(Boolean.TRUE.equals(entry.get("underlined")))
                .withStrikethrough(Boolean.TRUE.equals(entry.get("strikethrough")))
                .withObfuscated(Boolean.TRUE.equals(entry.get("obfuscated")))
                .withColor(color.startsWith("#")
                    ? TextColor.fromRgb(Integer.parseInt(color.substring(1), 16))
                    : TextColor.fromLegacyFormat(color.equals("gray") ? ChatFormatting.GRAY : ChatFormatting.WHITE));
                if (clickTarget != null) styled = styled.withClickEvent(new ClickEvent.OpenUrl(clickTarget));
                if (hoverLabel != null) styled = styled.withHoverEvent(
                    new HoverEvent.ShowText(Component.literal(hoverLabel))
                );
                return styled;
            });
            output.append(fragment);
        }
        return Optional.of(output);
    }

    private static URI safeUrl(String url) {
        if (url.length() > 512 || !url.matches("[\\x21-\\x7E]+")) return null;
        try {
            URI parsed = URI.create(url);
            if (!"http".equalsIgnoreCase(parsed.getScheme())
                && !"https".equalsIgnoreCase(parsed.getScheme())) return null;
            String hostname = parsed.getHost();
            if (hostname == null || parsed.getUserInfo() != null) return null;
            String host = hostname.toLowerCase(Locale.ROOT);
            if (host.equals("localhost") || host.endsWith(".localhost")
                || host.endsWith(".local") || host.endsWith(".internal")
                || !host.contains(".") || host.contains(":")
                || host.matches("[0-9.]+")) return null;
            return parsed;
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }
}
