package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class PublicPlayerCommandPolicyTest {
    @Test
    void acceptsOnlyIntentionallyPublicPlayerCommands() {
        assertEquals("/say hello", PublicPlayerCommandPolicy.sanitize("say hello"));
        assertEquals("/me waves", PublicPlayerCommandPolicy.sanitize("/me waves"));
        assertEquals("/list", PublicPlayerCommandPolicy.sanitize("list"));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("msg Steve private"));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("login secret"));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("tellraw @a[tag=secret] hi"));
        assertEquals("/tellraw @a {\"text\":\"hello\"}",
            PublicPlayerCommandPolicy.sanitize("tellraw @a {\"text\":\"hello\"}"));
    }

    @Test
    void rejectsOverlongOrInjectedCommandsAndMassPings() {
        assertEquals("", PublicPlayerCommandPolicy.sanitize("say " + "x".repeat(1900)));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("say hi\n/op Steve"));
        assertEquals("/say [everyone]", PublicPlayerCommandPolicy.sanitize("say @everyone"));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("msg @a private"));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("teammsg hidden"));
        assertEquals("", PublicPlayerCommandPolicy.sanitize("w Steve password"));
    }
}
