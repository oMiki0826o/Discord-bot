package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class SourceCommandTrackerTest {
    @Test
    void attachesExactPublicSayAndMeSourceOnlyOnce() {
        SourceCommandTracker tracker = new SourceCommandTracker();
        tracker.observe("Steve", "say hello");
        assertEquals("say", tracker.consume("Steve", "hello"));
        assertEquals("broadcast", tracker.consume("Steve", "hello"));
        tracker.observe("Steve", "/me waves");
        assertEquals("me", tracker.consume("Steve", "waves"));
    }

    @Test
    void neverTagsPrivateOrMismatchedMessages() {
        SourceCommandTracker tracker = new SourceCommandTracker();
        tracker.observe("Steve", "msg Alex private");
        tracker.observe("Steve", "say public");
        assertEquals("broadcast", tracker.consume("Steve", "private"));
        assertEquals("broadcast", tracker.consume("Alex", "public"));
        assertEquals("say", tracker.consume("Steve", "public"));
    }
}
