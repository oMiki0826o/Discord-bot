package io.miki.dmcc.bridge;

import net.minecraft.network.chat.Component;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Optional native Minecraft-to-Minecraft message formatting, parsed with the
 * same constrained component whitelist as authenticated Discord rich messages.
 * Never accepts arbitrary click events or raw JSON from player text.
 */
final class NativeRichText {
    private static final int MAX_BODY = 1400;
    private static final int MAX_PARTS = 110;

    private NativeRichText() { }

    static Component format(String prefix, String content) {
        String body = normalize(content, MAX_BODY);
        List<Map<String, Object>> segments = new ArrayList<>();
        add(segments, prefix, "white", "");
        StringBuilder plain = new StringBuilder();

        for (int i = 0; i < body.length() && segments.size() < MAX_PARTS; ) {
            String symbol = null;
            String style = null;
            if (body.startsWith("**", i)) { symbol = "**"; style = "bold"; }
            else if (body.startsWith("__", i)) { symbol = "__"; style = "underlined"; }
            else if (body.startsWith("~~", i)) { symbol = "~~"; style = "strikethrough"; }
            else if (body.startsWith("||", i)) { symbol = "||"; style = "obfuscated"; }
            else if (body.startsWith("`", i)) { symbol = "`"; style = "code"; }
            else if (body.startsWith("*", i)) { symbol = "*"; style = "italic"; }
            if (symbol != null) {
                int end = body.indexOf(symbol, i + symbol.length());
                if (end >= i + symbol.length() && end - i <= 520) {
                    flush(segments, plain);
                    add(segments, body.substring(i + symbol.length(), end),
                        style.equals("code") ? "gray" : "white", style);
                    i = end + symbol.length();
                    continue;
                }
            }
            if (body.startsWith("[", i)) {
                int middle = body.indexOf("](", i + 1);
                if (middle > i && middle - i < 122) {
                    int end = body.indexOf(')', middle + 2);
                    if (end > middle && end - middle < 515) {
                        String label = body.substring(i + 1, middle);
                        String url = body.substring(middle + 2, end);
                        if (url.startsWith("https://") || url.startsWith("http://")) {
                            flush(segments, plain);
                            segments.add(Map.of(
                                "text", label, "color", "#3366CC",
                                "underlined", true, "click_url", url, "hover_text", url
                            ));
                            i = end + 1;
                            continue;
                        }
                    }
                }
            }
            plain.append(body.charAt(i++));
        }
        flush(segments, plain);
        if (segments.isEmpty()) return Component.literal(prefix + body);
        return RichTextComponents.parse(Map.of("segments", segments))
            .map(component -> (Component) component)
            .orElseGet(() -> Component.literal(prefix + body));
    }

    private static String normalize(String source, int length) {
        if (source == null) return "";
        String text = source.replaceAll("[\\p{Cntrl}]", " ")
            .replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]");
        return text.length() > length ? text.substring(0, length) : text;
    }

    private static void flush(List<Map<String, Object>> parts, StringBuilder plain) {
        if (!plain.isEmpty()) {
            add(parts, plain.toString(), "white", "");
            plain.setLength(0);
        }
    }

    private static void add(
        List<Map<String, Object>> parts, String text, String color, String style
    ) {
        if (text == null || text.isEmpty()) return;
        Map<String, Object> result = new java.util.HashMap<>();
        result.put("text", text);
        result.put("color", color);
        if (!style.isEmpty() && !style.equals("code")) result.put(style, true);
        parts.add(result);
    }
}
