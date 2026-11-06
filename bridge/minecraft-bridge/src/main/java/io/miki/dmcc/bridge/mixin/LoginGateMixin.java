package io.miki.dmcc.bridge.mixin;

import com.mojang.authlib.GameProfile;
import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.network.Connection;
import net.minecraft.server.network.ServerLoginPacketListenerImpl;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Optional DMCC link check before vanilla completes login.
 *
 * A missing, unhealthy, or unresponsive Gateway never blocks admission.
 * The Bridge remains responsible only for a transient 5-second hold.
 */
@Mixin(ServerLoginPacketListenerImpl.class)
final class LoginGateMixin {
    @Shadow @Final private Connection connection;

    @Inject(method = "verifyLoginAndFinishConnectionSetup", at = @At("HEAD"), cancellable = true)
    private void dmccCheckVerifiedLink(GameProfile profile, CallbackInfo callback) {
        if (BridgeMod.shouldHoldLogin(
            (ServerLoginPacketListenerImpl) (Object) this, connection, profile
        )) {
            callback.cancel();
        }
    }
}
