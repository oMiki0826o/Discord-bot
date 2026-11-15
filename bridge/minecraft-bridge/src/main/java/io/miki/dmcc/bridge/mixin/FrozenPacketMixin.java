package io.miki.dmcc.bridge.mixin;

import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Keep an optionally frozen unlinked player at a safe anchor.
 * Chat and slash commands remain available for linking and assistance.
 */
@Mixin(ServerGamePacketListenerImpl.class)
final class FrozenPacketMixin {
    @Shadow public ServerPlayer player;

    @Inject(method = "handleMovePlayer", at = @At("HEAD"), cancellable = true)
    private void dmccPreventFrozenMovement(CallbackInfo callback) {
        if (BridgeMod.isFrozenPlayer(player)) {
            callback.cancel();
            BridgeMod.correctFrozenPlayer(player);
        }
    }

    @Inject(
        method = {
            "handlePlayerAction", "handleUseItem", "handleUseItemOn", "handleAttack",
            "handleInteract", "handleSetCarriedItem", "handleSetCreativeModeSlot",
            "handleContainerClick", "handleContainerButtonClick", "handlePlaceRecipe",
            "handleMoveVehicle", "handlePaddleBoat", "handlePlayerInput",
            "handlePlayerCommand", "handleTeleportToEntityPacket"
        },
        at = @At("HEAD"), cancellable = true, require = 0
    )
    private void dmccPreventFrozenInteractions(CallbackInfo callback) {
        if (BridgeMod.isFrozenPlayer(player)) callback.cancel();
    }
}
