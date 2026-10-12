package io.miki.dmcc.bridge.mixin;

import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.server.commands.GameModeCommand;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.GameType;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Emits the upstream DMCC game-mode event without coupling the Bridge to Discord. */
@Mixin(GameModeCommand.class)
final class GameModeCommandMixin {
    @Inject(
        method = "setGameMode(Lnet/minecraft/commands/CommandSourceStack;Lnet/minecraft/server/level/ServerPlayer;Lnet/minecraft/world/level/GameType;)Z",
        at = @At("HEAD")
    )
    private static void onSetGameMode(
        CommandSourceStack source,
        ServerPlayer player,
        GameType gameType,
        CallbackInfoReturnable<Boolean> callback
    ) {
        BridgeMod.relayGameModeChange(player, gameType);
    }
}
