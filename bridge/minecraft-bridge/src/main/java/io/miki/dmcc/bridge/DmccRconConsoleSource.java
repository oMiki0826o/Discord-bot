package io.miki.dmcc.bridge;

import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.rcon.RconConsoleSource;

/** Captures Minecraft command feedback for a DMCC request/response envelope. */
final class DmccRconConsoleSource extends RconConsoleSource {
    private final StringBuilder response = new StringBuilder();

    DmccRconConsoleSource(MinecraftServer server) {
        super(server);
    }

    @Override
    public String getCommandResponse() {
        return response.toString();
    }

    @Override
    public void sendSystemMessage(Component message) {
        if (!response.isEmpty()) response.append('\n');
        response.append(message.getString());
    }
}
