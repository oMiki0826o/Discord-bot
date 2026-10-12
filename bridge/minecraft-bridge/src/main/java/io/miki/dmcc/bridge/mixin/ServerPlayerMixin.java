package io.miki.dmcc.bridge.mixin;

import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.damagesource.DamageSource;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Emits a raw Minecraft death message before the player state is cleared. */
@Mixin(ServerPlayer.class)
final class ServerPlayerMixin {
    @Inject(method = "die", at = @At("HEAD"))
    private void onDie(DamageSource source, CallbackInfo callback) {
        BridgeMod.relayDeath((ServerPlayer) (Object) this);
    }
}
