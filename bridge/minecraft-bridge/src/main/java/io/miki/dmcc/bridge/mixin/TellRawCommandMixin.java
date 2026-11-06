package io.miki.dmcc.bridge.mixin;

import com.mojang.brigadier.context.CommandContext;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.arguments.ComponentArgument;
import net.minecraft.commands.arguments.EntityArgument;
import net.minecraft.server.commands.TellRawCommand;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Observe the native parsed tellraw command; forwarding never overwrites or
 * cancels vanilla behavior. A filtered selector cannot be treated as public.
 */
@Mixin(TellRawCommand.class)
final class TellRawCommandMixin {
    @Inject(method = "lambda$register$0", at = @At("HEAD"), require = 0)
    private static void dmccObservePublicTellraw(
        CommandContext<CommandSourceStack> context, CallbackInfoReturnable<Integer> callback
    ) throws CommandSyntaxException {
        if (!BridgeMod.isPublicTellrawCommand(context.getInput())) return;
        ServerPlayer recipient = EntityArgument.getPlayers(context, "targets")
            .stream().findFirst().orElse(null);
        if (recipient == null) return;
        Component message = ComponentArgument.getResolvedComponent(context, "message", recipient);
        BridgeMod.relayTellrawCommand(
            context.getSource().getTextName(), message
        );
    }
}
