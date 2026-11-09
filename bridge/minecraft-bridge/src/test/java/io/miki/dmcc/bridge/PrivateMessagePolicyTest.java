package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class PrivateMessagePolicyTest {
    @Test
    void vanillaMsgTellAndWAreRecognizedWithoutLeakingPrivateTargets() {
        assertTrue(PrivateMessagePolicy.isVanillaAlias("/msg Steve secret"));
        assertTrue(PrivateMessagePolicy.isVanillaAlias("tell Steve secret"));
        assertTrue(PrivateMessagePolicy.isVanillaAlias("/w @a hello"));
        assertFalse(PrivateMessagePolicy.isVanillaAlias("teammsg Steve secret"));
        assertFalse(PrivateMessagePolicy.isVanillaAlias("execute run msg Steve secret"));
        assertTrue(PrivateMessagePolicy.isAllPlayersMessage("/msg @a hello"));
        assertFalse(PrivateMessagePolicy.isAllPlayersMessage("/msg @a[tag=admin] hi"));
        assertFalse(PrivateMessagePolicy.isAllPlayersMessage("/msg Steve secret"));
    }
}
