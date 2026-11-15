package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class PublicTellrawPolicyTest {
    @Test
    void onlyExplicitAllPlayerTargetIsPublic() {
        assertTrue(PublicTellrawPolicy.isPublicBroadcast("tellraw @a {\"text\":\"hello\"}"));
        assertTrue(PublicTellrawPolicy.isPublicBroadcast("/tellraw @a {\"text\":\"hello\"}"));
        assertFalse(PublicTellrawPolicy.isPublicBroadcast("tellraw Steve {\"text\":\"private\"}"));
        assertFalse(PublicTellrawPolicy.isPublicBroadcast("tellraw @p {\"text\":\"private\"}"));
        assertFalse(PublicTellrawPolicy.isPublicBroadcast("tellraw @a[tag=admin] {\"text\":\"private\"}"));
        assertFalse(PublicTellrawPolicy.isPublicBroadcast("execute as Steve run tellraw @a {\"text\":\"foo\"}"));
        assertFalse(PublicTellrawPolicy.isPublicBroadcast("tellraw @a"));
    }

    @Test
    void onlyForwardsIdenticalMessagesForAllResolvedRecipients() {
        assertEquals(java.util.Optional.of("All players"),
            PublicTellrawPolicy.consensus(java.util.List.of("All players", "All players")));
        assertEquals(java.util.Optional.empty(),
            PublicTellrawPolicy.consensus(java.util.List.of("hello Steve", "hello Alex")));
        assertEquals(java.util.Optional.empty(),
            PublicTellrawPolicy.consensus(java.util.List.of()));
        assertEquals(java.util.Optional.empty(),
            PublicTellrawPolicy.consensus(java.util.Collections.nCopies(65, "large audience")));
    }

    @Test
    void boundsPublicMessageAndStripsDangerousPings() {
        assertEquals("hello", PublicTellrawPolicy.sanitize("hello"));
        assertEquals("[everyone]", PublicTellrawPolicy.sanitize("@everyone"));
        assertEquals("[here]", PublicTellrawPolicy.sanitize("@here"));
        assertEquals("", PublicTellrawPolicy.sanitize(""));
        assertTrue(PublicTellrawPolicy.sanitize("x".repeat(5000)).length() <= 1500);
    }
}
