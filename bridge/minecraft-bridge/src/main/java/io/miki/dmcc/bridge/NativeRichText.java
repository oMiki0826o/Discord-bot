package io.miki.dmcc.bridge;

import net.minecraft.network.chat.Component;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

/**
 * Optional native Minecraft-to-Minecraft message formatting, parsed with the
 * same constrained component whitelist as authenticated Discord rich messages.
 * Never accepts arbitrary click events or raw JSON from player text.
 */
final class NativeRichText {
    private static final int MAX_BODY = 1400;
    private static final int MAX_PARTS = 110;
    private static final Pattern TIMESTAMP = Pattern.compile("<t:(-?[0-9]{1,12})(?::[tTdDfFRsS])?>");
    private static final Pattern EMOJI = Pattern.compile(":([A-Za-z0-9_]{1,32}):");
    private static final Pattern USER = Pattern.compile("@([A-Za-z0-9_]{3,16})");
    private static final DateTimeFormatter DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'")
        .withZone(ZoneOffset.UTC);

    private NativeRichText() { }

    static Component format(String prefix, String content) {
        return format(prefix, content, NativeFormatPolicy.defaults());
    }

    static Component format(String prefix, String content, NativeFormatPolicy policy) {
        if (policy == null) policy = NativeFormatPolicy.defaults();
        String body = normalize(content, MAX_BODY);
        if (policy.timestamps()) body = renderTimestamps(body);
        if (policy.customEmojis()) body = renderEmojis(body, policy.emojiAliases());
        if (!policy.unicodeEmojis()) body = muteUnicodeEmoji(body);
        List<Map<String, Object>> segments = new ArrayList<>();
        add(segments, prefix, "white", "");
        StringBuilder plain = new StringBuilder();

        for (int i = 0; i < body.length() && segments.size() < MAX_PARTS; ) {
            String symbol = null;
            String style = null;
            if (policy.markdown()) {
                if (body.startsWith("**", i)) { symbol = "**"; style = "bold"; }
                else if (body.startsWith("__", i)) { symbol = "__"; style = "underlined"; }
                else if (body.startsWith("~~", i)) { symbol = "~~"; style = "strikethrough"; }
                else if (body.startsWith("||", i)) { symbol = "||"; style = "obfuscated"; }
                else if (body.startsWith("`", i)) { symbol = "`"; style = "code"; }
                else if (body.startsWith("*", i)) { symbol = "*"; style = "italic"; }
            }
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
            if (policy.hyperlinks() && body.startsWith("[", i)) {
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
            if (policy.mentions() && body.charAt(i) == '@') {
                Matcher matched = USER.matcher(body);
                matched.region(i, body.length());
                if (matched.lookingAt()) {
                    flush(segments, plain);
                    add(segments, matched.group(), "yellow", "");
                    i = matched.end();
                    continue;
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

    private static String renderTimestamps(String text) {
        Matcher matcher = TIMESTAMP.matcher(text);
        StringBuffer output = new StringBuffer();
        while (matcher.find()) {
            String rendered;
            try {
                rendered = DATE.format(Instant.ofEpochSecond(Long.parseLong(matcher.group(1))));
            } catch (RuntimeException invalid) {
                rendered = "[timestamp]";
            }
            matcher.appendReplacement(output, Matcher.quoteReplacement(rendered));
        }
        matcher.appendTail(output);
        return output.toString();
    }

    private static String renderEmojis(String text, Map<String, String> aliases) {
        Matcher matcher = EMOJI.matcher(text);
        StringBuffer output = new StringBuffer();
        while (matcher.find()) {
            String replacement = aliases.getOrDefault(
                matcher.group(1).toLowerCase(java.util.Locale.ROOT), matcher.group()
            );
            matcher.appendReplacement(output, Matcher.quoteReplacement(replacement));
        }
        matcher.appendTail(output);
        return output.toString();
    }

    private static String muteUnicodeEmoji(String text) {
        StringBuilder output = new StringBuilder();
        text.codePoints().forEach(code -> {
            if (code >= 0x2600 && Character.getType(code) == Character.OTHER_SYMBOL) {
                output.append("[emoji]");
            } else {
                output.appendCodePoint(code);
            }
        });
        return output.toString();
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
