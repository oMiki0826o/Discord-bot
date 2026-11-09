package io.miki.dmcc.bridge;

import net.minecraft.network.chat.Component;
import java.net.URI;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Bounded nested inline Markdown/hover parser for optional native chat overwrite.
 * All clickable links are independently validated by RichTextComponents; no
 * RunCommand, SuggestCommand, external JSON or NBT component is accepted.
 */
final class NativeRichText {
    private static final int MAX_BODY = 1400;
    private static final int MAX_PARTS = 110;
    private static final Pattern TIMESTAMP = Pattern.compile("<t:(-?[0-9]{1,12})(?::[tTdDfFRsS])?>");
    private static final Pattern EMOJI = Pattern.compile(":([A-Za-z0-9_]{1,32}):");
    private static final Pattern USER = Pattern.compile("@([A-Za-z0-9_]{3,16})");
    private static final Pattern LINK = Pattern.compile(
        "\\[([^\\]\\r\\n]{1,120})\\]\\((https?://[^\\s<>()]{1,500})\\)"
    );
    private static final Pattern RAW_LINK = Pattern.compile("https?://[^\\s<>\\x22\\x27\\x60]{1,500}");
    private static final DateTimeFormatter DATE = DateTimeFormatter
        .ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneOffset.UTC);

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
        List<Map<String, Object>> pieces = new ArrayList<>();
        add(pieces, normalize(prefix, 90), "white", false, false, false, false, null, null);
        boolean bold = false, italic = false, underlined = false, strike = false, code = false;
        StringBuilder buffer = new StringBuilder();
        for (int i = 0; i < body.length() && pieces.size() < MAX_PARTS;) {
            if (policy.markdown() && !code && body.startsWith("||", i)) {
                int end = body.indexOf("||", i + 2);
                if (end > i + 2) {
                    flush(pieces, buffer, bold, italic, underlined, strike, code);
                    add(pieces, "[spoiler]", "gray", false, false, true, false,
                        null, normalize(body.substring(i + 2, end), 480));
                    i = end + 2;
                    continue;
                }
            }
            if (policy.hyperlinks() && !code) {
                Matcher link = LINK.matcher(body);
                link.region(i, body.length());
                Matcher bare = RAW_LINK.matcher(body);
                bare.region(i, body.length());
                if (link.lookingAt() || bare.lookingAt()) {
                    String label;
                    // Do not infer interactivity from arbitrary text. Both URL
                    // forms pass the exact same restricted URL policy.
                    boolean bracketed = link.lookingAt();
                    String url = bracketed ? link.group(2) : bare.group();
                    label = bracketed ? link.group(1) : url.replaceAll("[.,;!?)]+$", "");
                    if (safeExternalUrl(url)) {
                        flush(pieces, buffer, bold, italic, underlined, strike, code);
                        add(pieces, label, "#3366CC", bold, italic, true, strike, url, url);
                        i += bracketed ? link.group().length() : bare.group().length();
                        continue;
                    }
                }
            }
            if (policy.markdown() && body.charAt(i) == '\\'
                && i + 1 < body.length() && "*_~`|\\[]()".indexOf(body.charAt(i + 1)) >= 0) {
                buffer.append(body.charAt(i + 1));
                i += 2;
                continue;
            }
            String mark = null;
            if (policy.markdown()) {
                if (body.startsWith("`", i)) mark = "`";
                else if (!code) {
                    for (String candidate : new String[]{"**", "__", "~~", "*", "_"}) {
                        if (body.startsWith(candidate, i)) { mark = candidate; break; }
                    }
                }
            }
            if (mark != null) {
                boolean active = switch (mark) {
                    case "**" -> bold;
                    case "__" -> underlined;
                    case "~~" -> strike;
                    case "*", "_" -> italic;
                    default -> code;
                };
                if (active || body.indexOf(mark, i + mark.length()) >= 0) {
                    flush(pieces, buffer, bold, italic, underlined, strike, code);
                    switch (mark) {
                        case "**" -> bold = !bold;
                        case "__" -> underlined = !underlined;
                        case "~~" -> strike = !strike;
                        case "*", "_" -> italic = !italic;
                        default -> code = !code;
                    }
                    i += mark.length();
                    continue;
                }
            }
            if (policy.mentions() && !code && body.charAt(i) == '@') {
                Matcher m = USER.matcher(body);
                m.region(i, body.length());
                if (m.lookingAt()) {
                    flush(pieces, buffer, bold, italic, underlined, strike, code);
                    add(pieces, m.group(), "yellow", bold, italic, underlined, strike, null, null);
                    i = m.end();
                    continue;
                }
            }
            buffer.append(body.charAt(i++));
        }
        flush(pieces, buffer, bold, italic, underlined, strike, code);
        if (pieces.isEmpty()) return Component.literal("");
        return RichTextComponents.parse(Map.of("segments", pieces))
            .orElseGet(() -> Component.literal(normalize(prefix, 90) + body));
    }

    private static boolean safeExternalUrl(String text) {
        try {
            URI uri = URI.create(text);
            if (!"http".equalsIgnoreCase(uri.getScheme())
                && !"https".equalsIgnoreCase(uri.getScheme())) return false;
            String host = uri.getHost();
            if (host == null || uri.getUserInfo() != null || uri.getPort() > 65535) return false;
            host = host.toLowerCase(Locale.ROOT);
            if (host.equals("localhost") || host.endsWith(".local")
                || host.endsWith(".localhost") || host.endsWith(".internal")
                || host.matches("[0-9.]+") || !host.contains(".")) return false;
            return text.length() <= 512 && text.chars().noneMatch(c -> c < 33 || c > 126);
        } catch (IllegalArgumentException invalid) {
            return false;
        }
    }

    private static void flush(
        List<Map<String, Object>> pieces, StringBuilder buffer,
        boolean bold, boolean italic, boolean underline, boolean strike, boolean code
    ) {
        if (!buffer.isEmpty()) {
            add(pieces, buffer.toString(), code ? "gray" : "white",
                !code && bold, !code && italic, !code && underline,
                !code && strike, null, null);
            buffer.setLength(0);
        }
    }

    private static void add(
        List<Map<String, Object>> pieces, String value, String color,
        boolean bold, boolean italic, boolean underline, boolean strike,
        String click, String hover
    ) {
        if (value == null || value.isEmpty() || pieces.size() >= MAX_PARTS) return;
        Map<String, Object> part = new HashMap<>();
        part.put("text", value);
        part.put("color", color);
        part.put("bold", bold);
        part.put("italic", italic);
        part.put("underlined", underline);
        part.put("strikethrough", strike);
        if (click != null) part.put("click_url", click);
        if (hover != null) part.put("hover_text", hover);
        pieces.add(part);
    }

    private static String renderTimestamps(String text) {
        Matcher matcher = TIMESTAMP.matcher(text);
        StringBuffer result = new StringBuffer();
        while (matcher.find()) {
            String rendered;
            try {
                rendered = DATE.format(Instant.ofEpochSecond(Long.parseLong(matcher.group(1))));
            } catch (RuntimeException invalid) {
                rendered = "[timestamp]";
            }
            matcher.appendReplacement(result, Matcher.quoteReplacement(rendered));
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static String renderEmojis(String text, Map<String, String> aliases) {
        Matcher matcher = EMOJI.matcher(text);
        StringBuffer result = new StringBuffer();
        while (matcher.find()) {
            String replacement = aliases.getOrDefault(
                matcher.group(1).toLowerCase(Locale.ROOT), matcher.group()
            );
            matcher.appendReplacement(result, Matcher.quoteReplacement(replacement));
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static String muteUnicodeEmoji(String text) {
        StringBuilder out = new StringBuilder();
        text.codePoints().forEach(code -> {
            if (code >= 0x2600 && Character.getType(code) == Character.OTHER_SYMBOL) {
                out.append("[emoji]");
            } else {
                out.appendCodePoint(code);
            }
        });
        return out.toString();
    }

    private static String normalize(String source, int max) {
        if (source == null) return "";
        String clean = source.replaceAll("[\\p{Cntrl}]", " ")
            .replaceAll("(?i)@everyone", "[everyone]")
            .replaceAll("(?i)@here", "[here]");
        return clean.length() > max ? clean.substring(0, max) : clean;
    }
}
