package io.miki.dmcc.bridge.mixin;

import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.network.chat.LastSeenMessages;
import net.minecraft.network.protocol.game.ServerboundChatCommandSignedPacket;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Observe only the server's command-execution boundary. A separate strict
 * allowlist determines which commands may leave the Minecraft process.
 */
@Mixin(ServerGamePacketListenerImpl.class)
abstract class PlayerCommandMixin {
    @Shadow public ServerPlayer player;

    @Inject(method = "performUnsignedChatCommand", at = @At("HEAD"), require = 0)
    private void dmccUnsignedCommand(String command, CallbackInfo callback) {
        BridgeMod.relayPlayerCommand(player, command);
    }

    @Inject(method = "performSignedChatCommand", at = @At("HEAD"), require = 0)
    private void dmccSignedCommand(
        ServerboundChatCommandSignedPacket packet, LastSeenMessages messages, CallbackInfo callback
    ) {
        BridgeMod.relayPlayerCommand(player, packet.command());
    }
}
