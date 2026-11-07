package io.miki.dmcc.bridge.mixin;

import com.mojang.brigadier.context.CommandContext;
import io.miki.dmcc.bridge.BridgeMod;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.network.chat.PlayerChatMessage;
import net.minecraft.server.commands.SayCommand;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Select only the public /say execution handler: the generic Fabric command
 * message callback can contain recipient-scoped /msg and must not be mirrored.
 */
@Mixin(SayCommand.class)
abstract class SayCommandMixin {
    @Inject(method = "lambda$register$1", at = @At("HEAD"), cancellable = true, require = 0)
    private static void dmccPublicSay(
        CommandContext<CommandSourceStack> context,
        PlayerChatMessage message,
        CallbackInfo callback
    ) {
        if (BridgeMod.relayPublicSay(context.getSource(), message.signedContent())) {
            callback.cancel();
        }
    }
}
