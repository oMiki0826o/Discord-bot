package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.util.UUID;
import java.lang.reflect.Method;
import com.mojang.authlib.GameProfile;
import org.junit.jupiter.api.Test;

/** Verify the login gate reads actual Authlib profiles for both Minecraft toolchains. */
class LinkGateProfileTest {
    @Test
    void resolvesAuthenticatedProfileUuidAndName() throws Exception {
        UUID uuid = UUID.fromString("123e4567-e89b-12d3-a456-426614174000");
        GameProfile profile = new GameProfile(uuid, "Steve");
        Method readId = BridgeMod.class.getDeclaredMethod("profileIdentifier", GameProfile.class);
        Method readName = BridgeMod.class.getDeclaredMethod("profileName", GameProfile.class);
        readId.setAccessible(true);
        readName.setAccessible(true);
        assertEquals(uuid, readId.invoke(null, profile));
        assertEquals("Steve", readName.invoke(null, profile));
    }
}
