package io.miki.dmcc.bridge;

import com.mojang.authlib.GameProfile;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

/**
 * Authenticated, opt-in Minecraft-native operator changes on the server thread.
 *
 * Avoids a generated source dependency across 1.21.8's GameProfile and
 * 1.21.9's NameAndId. Only DMCC-owned entries may be updated or removed;
 * operators created by other admins are never overwritten.
 */
final class OpSyncApplier {
    private final Set<UUID> managed = new HashSet<>();

    int apply(MinecraftServer server, OpSyncPolicy policy) {
        int applied = 0;
        for (OpSyncPolicy.Entry entry : policy.entries()) {
            try {
                if (applyOne(server, entry, policy.allowRemovals())) applied++;
            } catch (ReflectiveOperationException | SecurityException | IllegalArgumentException error) {
                BridgeMod.LOGGER.warn(
                    "DMCC operator sync skipped UUID={} ({})",
                    entry.playerId(), error.getClass().getSimpleName()
                );
            }
        }
        return applied;
    }

    private boolean applyOne(MinecraftServer server, OpSyncPolicy.Entry entry, boolean removals)
        throws ReflectiveOperationException {
        Object list = server.getPlayerList();
        Object ops = server.getPlayerList().getOps();
        Object principal = principal(entry.playerId(), entry.playerName());
        Method get = lookup(ops.getClass(), "get", principal.getClass());
        if (get == null) throw new NoSuchMethodException("ServerOpList.get");
        Object existing = get.invoke(ops, principal);
        if (existing != null && !managed.contains(entry.playerId())) {
            // Never overwrite a preexisting manually granted operator.
            return false;
        }
        if (entry.level() == 0) {
            if (!removals || !managed.contains(entry.playerId()) || existing == null) {
                return false;
            }
            Method remove = lookup(ops.getClass(), "remove", principal.getClass());
            if (remove == null) throw new NoSuchMethodException("ServerOpList.remove");
            remove.invoke(ops, principal);
            managed.remove(entry.playerId());
            refresh(server, entry.playerId());
            return true;
        }
        if (existing != null) {
            Method level = existing.getClass().getMethod("getLevel");
            Object value = level.invoke(existing);
            if (value instanceof Number number && number.intValue() == entry.level()) {
                return false;
            }
        }
        Class<?> entryType = Class.forName("net.minecraft.server.players.ServerOpListEntry");
        Constructor<?> constructor = entryType.getConstructor(
            principal.getClass(), int.class, boolean.class
        );
        boolean bypass = false;
        if (existing != null) {
            bypass = Boolean.TRUE.equals(
                existing.getClass().getMethod("getBypassesPlayerLimit").invoke(existing)
            );
        }
        Object next = constructor.newInstance(principal, entry.level(), bypass);
        Method add = lookup(ops.getClass(), "add", entryType);
        if (add == null) throw new NoSuchMethodException("ServerOpList.add");
        add.invoke(ops, next);
        managed.add(entry.playerId());
        refresh(server, entry.playerId());
        return true;
    }

    private static Object principal(UUID uuid, String playerName) throws ReflectiveOperationException {
        try {
            Class<?> modern = Class.forName("net.minecraft.server.players.NameAndId");
            return modern.getConstructor(UUID.class, String.class).newInstance(uuid, playerName);
        } catch (ClassNotFoundException oldMinecraft) {
            return new GameProfile(uuid, playerName);
        }
    }

    private static Method lookup(Class<?> target, String name, Class<?> actual) {
        for (Method method : target.getMethods()) {
            if (method.getName().equals(name) && method.getParameterCount() == 1
                && method.getParameterTypes()[0].isAssignableFrom(actual)) {
                return method;
            }
        }
        return null;
    }

    private static void refresh(MinecraftServer server, UUID uuid) {
        ServerPlayer player = server.getPlayerList().getPlayer(uuid);
        if (player != null) server.getCommands().sendCommands(player);
    }

    void clear() {
        managed.clear();
    }
}
