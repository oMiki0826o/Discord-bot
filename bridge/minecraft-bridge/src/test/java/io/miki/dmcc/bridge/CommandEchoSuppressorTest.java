package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class CommandEchoSuppressorTest {
    @Test
    void commandChatEchoIsSuppressedExactlyOnce() {
        var suppressor = new CommandEchoSuppressor();
        suppressor.mark("Steve", "Hello world");
        assertTrue(suppressor.consume("Steve", "Hello world"));
        assertFalse(suppressor.consume("Steve", "Hello world"));
        assertFalse(suppressor.consume("Alex", "Hello world"));
    }

    @Test
    void unrelatedChatIsNotSuppressed() {
        var suppressor = new CommandEchoSuppressor();
        suppressor.mark("Steve", "Hi from say");
        assertFalse(suppressor.consume("Steve", "Hello from chat"));
    }
}
