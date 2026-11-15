package io.miki.dmcc.bridge;

import com.mojang.authlib.GameProfile;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.io.IOException;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Authenticated, opt-in Minecraft-native operator changes on the server thread.
 *
 * Avoids a generated source dependency across 1.21.8's GameProfile and
 * 1.21.9's NameAndId. Only DMCC-owned entries may be updated or removed;
 * operators created by other admins are never overwritten.
 */
final class OpSyncApplier {
    private static final Logger LOGGER = LoggerFactory.getLogger("minecraft_bridge/op_sync");
    private ManagedOpLedger managed = ManagedOpLedger.inMemory();

    void configure(Path ledgerFile) throws IOException {
        managed = ManagedOpLedger.load(ledgerFile);
    }

    record ApplyReport(int updated, int failed) { }

    int apply(MinecraftServer server, OpSyncPolicy policy) {
        return applyWithReport(server, policy).updated();
    }

    ApplyReport applyWithReport(MinecraftServer server, OpSyncPolicy policy) {
        int applied = 0;
        int failed = 0;
        for (OpSyncPolicy.Entry entry : policy.entries()) {
            try {
                if (applyOne(server, entry, policy.allowRemovals())) applied++;
            } catch (ReflectiveOperationException | IOException | SecurityException | IllegalArgumentException error) {
                failed++;
                LOGGER.warn(
                    "DMCC operator sync skipped UUID={} ({})",
                    entry.playerId(), error.getClass().getSimpleName()
                );
            }
        }
        if (policy.allowRemovals() && policy.fullSnapshot()) {
            Set<UUID> included = new HashSet<>();
            policy.entries().forEach(entry -> included.add(entry.playerId()));
            for (var owner : managed.snapshot().entrySet()) {
                if (included.contains(owner.getKey())) continue;
                try {
                    var old = owner.getValue();
                    if (applyOne(server, new OpSyncPolicy.Entry(owner.getKey(), old.name(), 0), true)) {
                        applied++;
                    }
                } catch (ReflectiveOperationException | IOException | SecurityException | IllegalArgumentException error) {
                    failed++;
                    LOGGER.warn("DMCC skipped stale operator UUID={} ({})",
                        owner.getKey(), error.getClass().getSimpleName());
                }
            }
        }
        return new ApplyReport(applied, failed);
    }

    private boolean applyOne(MinecraftServer server, OpSyncPolicy.Entry entry, boolean removals)
        throws ReflectiveOperationException, IOException {
        Object ops = server.getPlayerList().getOps();
        Object principal = principal(entry.playerId(), entry.playerName());
        Method get = lookup(ops.getClass(), "get", principal.getClass());
        if (get == null) throw new NoSuchMethodException("ServerOpList.get");
        Object existing = get.invoke(ops, principal);
        ManagedOpLedger.Entry owned = managed.get(entry.playerId());
        if (existing != null && owned == null) {
            // Never adopt a preexisting manually granted operator.
            return false;
        }
        if (existing != null && owned != null) {
            Object rawLevel = existing.getClass().getMethod("getLevel").invoke(existing);
            if (!(rawLevel instanceof Number level) || level.intValue() != owned.level()) {
                // Someone modified this native operator; relinquish DMCC ownership.
                managed.remove(entry.playerId());
                return false;
            }
        }
        if (existing == null && owned != null) {
            managed.remove(entry.playerId());
            owned = null;
        }
        if (entry.level() == 0) {
            if (!removals || owned == null || existing == null) {
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
        managed.put(entry.playerId(), entry.playerName(), entry.level());
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
        // Never delete durable ownership on server shutdown.
        managed = ManagedOpLedger.inMemory();
    }
}
