package io.miki.dmcc.bridge.mixin;

import com.mojang.brigadier.context.CommandContext;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import io.miki.dmcc.bridge.BridgeMod;
import io.miki.dmcc.bridge.PrivateMessagePolicy;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.arguments.EntityArgument;
import net.minecraft.commands.arguments.MessageArgument;
import net.minecraft.server.commands.MsgCommand;
import net.minecraft.server.level.ServerPlayer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Exact vanilla /msg, /tell, /w command handler.
 *
 * Does not cancel or alter vanilla delivery. Direct targets are sent only to
 * the consent-scoped private Gateway event; a bare @a is a public source event.
 */
@Mixin(MsgCommand.class)
abstract class MsgCommandMixin {
    @Inject(method = "lambda$register$0", at = @At("HEAD"), require = 0)
    private static void dmccObserveVanillaPrivateCommand(
        CommandContext<CommandSourceStack> context, CallbackInfoReturnable<Integer> callback
    ) throws CommandSyntaxException {
        String input = context.getInput();
        if (!PrivateMessagePolicy.isVanillaAlias(input)) return;
        var recipients = EntityArgument.getPlayers(context, "targets");
        if (recipients.isEmpty()) return;
        boolean publicMessage = PrivateMessagePolicy.isAllPlayersMessage(input);
        MessageArgument.resolveChatMessage(context, "message", resolved -> {
            String text = resolved.signedContent();
            if (publicMessage) {
                BridgeMod.relayVanillaAllPlayersMessage(context.getSource(), text);
            } else if (recipients.size() == 1) {
                ServerPlayer sender;
                try {
                    sender = context.getSource().getPlayerOrException();
                } catch (CommandSyntaxException ignored) {
                    return; // Console is not a linked personal identity.
                }
                BridgeMod.relayVanillaPrivate(sender, recipients.iterator().next(), text);
            }
        });
    }
}
