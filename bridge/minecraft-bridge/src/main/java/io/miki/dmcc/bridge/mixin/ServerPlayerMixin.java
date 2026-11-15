package io.miki.dmcc.bridge.mixin;

import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.damagesource.DamageSource;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Emits a raw Minecraft death message before the player state is cleared. */
@Mixin(ServerPlayer.class)
final class ServerPlayerMixin {
    /**
     * Damage is suppressed only while an ephemeral freeze lease is active.
     * No permanent invulnerability flag is written to player NBT.
     */
    @Inject(method = "hurtServer", at = @At("HEAD"), cancellable = true)
    private void dmccProtectFrozenPlayer(
        ServerLevel world, DamageSource damage, float amount,
        CallbackInfoReturnable<Boolean> callback
    ) {
        if (BridgeMod.isFrozenPlayer((ServerPlayer) (Object) this)) {
            callback.setReturnValue(false);
        }
    }

    @Inject(method = "die", at = @At("HEAD"))
    private void onDie(DamageSource source, CallbackInfo callback) {
        BridgeMod.relayDeath((ServerPlayer) (Object) this);
    }
}
