package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class PlayerMentionRequestTest {
    @Test
    void validatesEightTargetsAndActionBar() {
        String user = "123e4567-e89b-12d3-a456-426614174000";
        var result = PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of(user), "style", "actionbar", "message", "Discord hello"
        ));
        assertTrue(result.isPresent());
        assertEquals(UUID.fromString(user), result.get().players().getFirst());
        assertEquals("Discord hello", result.get().message());
        assertTrue(result.get().actionBar());
    }

    @Test
    void refusesMalformedOrExcessiveTargets() {
        assertTrue(PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of("not-a-uuid"), "style", "chat", "message", "hi"
        )).isEmpty());
        assertTrue(PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of("123e4567-e89b-12d3-a456-426614174000"),
            "style", "command", "message", "hello"
        )).isEmpty());
        assertTrue(PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of(), "style", "chat", "message", "hi"
        )).isEmpty());
        assertTrue(PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of("123e4567-e89b-12d3-a456-426614174000"),
            "style", "chat", "message", ""
        )).isEmpty());
    }
    @Test
    void supportsTitleAndOptionalSoundWhileRejectingUnsafeAudioFields() {
        String user = "123e4567-e89b-12d3-a456-426614174000";
        var title = PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of(user), "style", "title",
            "sound", false, "message", "Discord ping"
        ));
        assertTrue(title.isPresent());
        assertEquals("title", title.get().style());
        assertFalse(title.get().sound());
        var oldPacket = PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of(user), "style", "chat", "message", "legacy"
        ));
        assertTrue(oldPacket.isPresent());
        assertTrue(oldPacket.get().sound());
        assertTrue(PlayerMentionRequest.parse(Map.of(
            "player_uuids", List.of(user), "style", "title",
            "sound", "command", "message", "hi"
        )).isEmpty());
    }
}

