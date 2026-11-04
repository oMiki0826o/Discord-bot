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
}
