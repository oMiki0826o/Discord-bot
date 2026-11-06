package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

final class NativeMessageFormatterTest {
    @Test
    void buildsBoundedNonInteractivePlayerChatReplacement() {
        var replacement = NativeMessageFormatter.playerChat("Steve", "Hello @everyone");
        assertEquals("<Steve> Hello [everyone]", replacement.getString());
        assertNull(replacement.getStyle().getClickEvent());
        assertTrue(replacement.getString().length() < 1500);
    }

    @Test
    void publicCommandsCannotInjectNewlinesOrCommands() {
        var replacement = NativeMessageFormatter.publicCommand("Server", "Restart\n/op Steve");
        assertFalse(replacement.getString().contains("\n"));
        assertTrue(replacement.getString().contains("Restart /op Steve"));
    }

    @Test
    void truncatesUntrustedIncomingText() {
        var replacement = NativeMessageFormatter.playerChat("A".repeat(5000), "B".repeat(5000));
        assertTrue(replacement.getString().length() <= 1500);
    }
}
