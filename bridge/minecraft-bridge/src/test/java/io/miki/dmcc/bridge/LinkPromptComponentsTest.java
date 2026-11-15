package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import net.minecraft.network.chat.Component;
import org.junit.jupiter.api.Test;

final class LinkPromptComponentsTest {
    @Test
    void generatedLinkCodeIsCopyableButNeverExecutesCommands() {
        Component prompt = LinkPromptComponents.linkCode("ABCDEF");
        assertTrue(prompt.getString().contains("ABCDEF"));
        assertTrue(prompt.getSiblings().stream()
            .anyMatch(item -> item.getStyle().getClickEvent() != null
                && item.getStyle().getHoverEvent() != null));
        assertFalse(prompt.getString().contains("password"));
    }

    @Test
    void maliciousOrMissingCodeCannotBecomeInteractive() {
        Component invalid = LinkPromptComponents.linkCode("X\n/op Steve");
        assertFalse(invalid.getString().contains("/op"));
        assertTrue(invalid.getSiblings().stream()
            .noneMatch(item -> item.getStyle().getClickEvent() != null));
    }

    @Test
    void unlinkHintCanOnlySuggestTheBuiltInCommand() {
        Component prompt = LinkPromptComponents.unlinkHint();
        assertTrue(prompt.getString().contains("/dmcc unlink"));
        assertNotNull(prompt.getSiblings().getFirst().getStyle().getClickEvent());
    }
}
