package io.miki.dmcc.bridge;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.HoverEvent;
import java.util.regex.Pattern;

/**
 * Internal Minecraft-only interactive help. Never exposes arbitrary Discord
 * content as a command, URL, or click action.
 */
final class LinkPromptComponents {
    private static final Pattern CODE = Pattern.compile("[A-Za-z0-9_-]{4,16}");

    private LinkPromptComponents() { }

    static Component linkCode(String code) {
        if (code == null || !CODE.matcher(code).matches()) {
            return Component.literal("DMCC: Link code unavailable. Try /dmcc link again.");
        }
        return Component.empty()
            .append(Component.literal("DMCC: Link code "))
            .append(Component.literal("[" + code + "]").withStyle(style -> style
                .withColor(ChatFormatting.AQUA)
                .withClickEvent(new ClickEvent.CopyToClipboard(code))
                .withHoverEvent(new HoverEvent.ShowText(
                    Component.literal("Click to copy this one-time code")))
            ))
            .append(Component.literal(" — paste it into Discord /dmcc link."));
    }

    static Component unlinkHint() {
        return Component.empty().append(
            Component.literal("/dmcc unlink").withStyle(style -> style
                .withColor(ChatFormatting.YELLOW)
                .withClickEvent(new ClickEvent.SuggestCommand("/dmcc unlink"))
                .withHoverEvent(new HoverEvent.ShowText(
                    Component.literal("Click to suggest the Minecraft unlink command")))
            )
        );
    }
}
