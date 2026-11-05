package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class RichTextComponentsTest {
    @Test
    void preservesSafeStyleAndText() {
        var parsed = RichTextComponents.parse(Map.of("segments", List.of(
            Map.of("text", "Hello ", "bold", false),
            Map.of("text", "Steve", "bold", true, "color", "gray")
        )));
        assertTrue(parsed.isPresent());
        assertEquals("Hello Steve", parsed.get().getString());
        assertTrue(parsed.get().getSiblings().get(1).getStyle().isBold());
    }

    @Test
    void rejectsUnknownFieldsAndHugeTexts() {
        assertTrue(RichTextComponents.parse(Map.of(
            "segments", List.of(Map.of("text", "hi", "clickEvent", "/op Steve"))
        )).isEmpty());
        assertTrue(RichTextComponents.parse(Map.of(
            "segments", List.of(Map.of("text", "x".repeat(2000)))
        )).isEmpty());
        assertTrue(RichTextComponents.parse(Map.of("segments", List.of())).isEmpty());
    }
    @Test
    void acceptsValidatedDiscordRoleColorButRejectsUntrustedColorStrings() {
        var parsed = RichTextComponents.parse(Map.of("segments", List.of(
            Map.of("text", "<Alex>", "color", "#Aa00fF")
        )));
        assertTrue(parsed.isPresent());
        assertEquals(0xAA00FF, parsed.get().getSiblings().getFirst().getStyle().getColor().getValue());
        assertTrue(RichTextComponents.parse(Map.of("segments", List.of(
            Map.of("text", "hello", "color", "#NN0000")
        ))).isEmpty());
        assertTrue(RichTextComponents.parse(Map.of("segments", List.of(
            Map.of("text", "hello", "color", "#123456;run_op")
        ))).isEmpty());
    }
    @Test
    void allowsHttpUrlAndHoverWithoutAllowingCommands() {
        var safe = RichTextComponents.parse(Map.of("segments", List.of(Map.of(
            "text", "Open docs", "color", "#3366CC",
            "click_url", "https://example.org/docs",
            "hover_text", "https://example.org/docs", "underlined", true
        ))));
        assertTrue(safe.isPresent());
        assertNotNull(safe.get().getSiblings().getFirst().getStyle().getClickEvent());
        assertNotNull(safe.get().getSiblings().getFirst().getStyle().getHoverEvent());
        assertTrue(RichTextComponents.parse(Map.of("segments", List.of(Map.of(
            "text", "bad", "click_url", "javascript:alert(1)"
        )))).isEmpty());
        assertTrue(RichTextComponents.parse(Map.of("segments", List.of(Map.of(
            "text", "bad", "click_url", "https://localhost/admin"
        )))).isEmpty());
    }
}


