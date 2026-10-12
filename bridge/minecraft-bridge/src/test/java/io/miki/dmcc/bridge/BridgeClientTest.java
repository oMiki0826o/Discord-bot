package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

/** Validates the Java Bridge handshake against a minimal Protocol v1 peer. */
final class BridgeClientTest {
    @Test
    void authenticationChallengeHasAnIndependentTimeout() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            CountDownLatch accepted = new CountDownLatch(1);
            CompletableFuture<Void> peer = CompletableFuture.runAsync(() -> {
                try (Socket ignored = server.accept()) {
                    accepted.countDown();
                    Thread.sleep(500);
                } catch (Exception exception) {
                    throw new RuntimeException(exception);
                }
            });
            BridgeSettings settings = new BridgeSettings(
                "survival", "127.0.0.1", server.getLocalPort(), "secret", 500, 50, 60_000, 120_000
            );
            BridgeClient client = new BridgeClient(settings);
            try {
                org.junit.jupiter.api.Assertions.assertThrows(SocketTimeoutException.class, client::connect);
                assertTrue(accepted.await(1, TimeUnit.SECONDS));
            } finally {
                client.close();
            }
            peer.get(2, TimeUnit.SECONDS);
        }
    }

    @Test
    void authenticatesWithAProtocolV1Gateway() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            CountDownLatch releasePeer = new CountDownLatch(1);
            CompletableFuture<Void> peer = CompletableFuture.runAsync(() -> serveOne(server, releasePeer));
            BridgeClient client = new BridgeClient(new BridgeSettings("survival", "127.0.0.1", server.getLocalPort(), "secret"));
            try {
                client.connect();
                assertEquals(BridgeClient.State.AUTHENTICATED, client.state());
            } finally {
                client.close();
                releasePeer.countDown();
            }
            peer.get(3, TimeUnit.SECONDS);
        }
    }

    @Test
    void deliversMinecraftMessageAfterAuthentication() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            CountDownLatch delivered = new CountDownLatch(1);
            CompletableFuture<Void> peer = CompletableFuture.runAsync(() -> serveMessage(server));
            BridgeClient client = new BridgeClient(
                new BridgeSettings("survival", "127.0.0.1", server.getLocalPort(), "secret"),
                (ignored, envelope) -> {
                    if (envelope.type().equals("minecraft_message")) delivered.countDown();
                }
            );
            try {
                client.connect();
                assertEquals(true, delivered.await(2, TimeUnit.SECONDS));
            } finally {
                client.close();
            }
            peer.get(3, TimeUnit.SECONDS);
        }
    }

    @Test
    void recordsUnexpectedMessageHandlerFailureBeforeDisconnecting() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            CompletableFuture<Void> peer = CompletableFuture.runAsync(() -> serveMessage(server));
            BridgeClient client = new BridgeClient(
                new BridgeSettings("survival", "127.0.0.1", server.getLocalPort(), "secret"),
                (ignored, envelope) -> { throw new IllegalStateException("handler failed"); }
            );
            client.connect();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
            while (client.state() != BridgeClient.State.DISCONNECTED && System.nanoTime() < deadline) {
                Thread.sleep(10);
            }

            assertEquals(BridgeClient.State.DISCONNECTED, client.state());
            assertEquals("handler failed", client.lastFailure().getMessage());
            peer.get(3, TimeUnit.SECONDS);
        }
    }

    @Test
    void concurrentSendAndCloseNeverExposeNullPointerException() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            CountDownLatch releasePeer = new CountDownLatch(1);
            CompletableFuture<Void> peer = CompletableFuture.runAsync(() -> serveOne(server, releasePeer));
            BridgeClient client = new BridgeClient(
                new BridgeSettings("survival", "127.0.0.1", server.getLocalPort(), "secret")
            );
            client.connect();
            AtomicReference<Throwable> unexpected = new AtomicReference<>();
            CompletableFuture<Void> sender = CompletableFuture.runAsync(() -> {
                for (int index = 0; index < 1_000; index++) {
                    try {
                        client.send(new ProtocolEnvelope(1, "ping", "survival", null, Map.of()));
                    } catch (java.io.IOException expected) {
                        return;
                    } catch (Throwable failure) {
                        unexpected.set(failure);
                        return;
                    }
                }
            });
            client.close();
            sender.get(3, TimeUnit.SECONDS);
            releasePeer.countDown();
            peer.get(3, TimeUnit.SECONDS);

            assertNull(unexpected.get());
            assertTrue(client.state() == BridgeClient.State.DISCONNECTED);
        }
    }

    @Test
    void closeInterruptsABlockedSocketWrite() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            CountDownLatch releasePeer = new CountDownLatch(1);
            CompletableFuture<Void> peer = CompletableFuture.runAsync(() -> serveOne(server, releasePeer));
            BridgeClient client = new BridgeClient(
                new BridgeSettings("survival", "127.0.0.1", server.getLocalPort(), "secret")
            );
            client.connect();
            String payload = "x".repeat(200_000);
            CountDownLatch sending = new CountDownLatch(1);
            CompletableFuture<Void> sender = CompletableFuture.runAsync(() -> {
                sending.countDown();
                try {
                    while (true) {
                        client.send(new ProtocolEnvelope(
                            1, "minecraft_message", "survival", null, Map.of("message", payload)
                        ));
                    }
                } catch (java.io.IOException expected) {
                    // Closing the socket is expected to unblock the pending write.
                }
            });
            assertTrue(sending.await(1, TimeUnit.SECONDS));
            Thread.sleep(100);

            CompletableFuture.runAsync(client::close).get(2, TimeUnit.SECONDS);
            sender.get(2, TimeUnit.SECONDS);
            releasePeer.countDown();
            peer.get(3, TimeUnit.SECONDS);
            assertEquals(BridgeClient.State.DISCONNECTED, client.state());
        }
    }

    private static void serveOne(ServerSocket server, CountDownLatch releasePeer) {
        try (Socket socket = server.accept()) {
            ProtocolEnvelope handshake = read(socket);
            if (!handshake.type().equals("handshake")) {
                throw new AssertionError("expected handshake");
            }
            write(socket, new ProtocolEnvelope(1, "challenge", "survival", null, Map.of("challenge", "challenge")));
            ProtocolEnvelope authentication = read(socket);
            if (!Authentication.createResponse("challenge", "secret").equals(authentication.data().get("response"))) {
                throw new AssertionError("bad HMAC response");
            }
            write(socket, new ProtocolEnvelope(1, "login_success", "survival", null, Map.of()));
            releasePeer.await(3, TimeUnit.SECONDS);
        } catch (Exception exception) {
            exception.printStackTrace();
            throw new RuntimeException(exception);
        }
    }

    private static void serveMessage(ServerSocket server) {
        try (Socket socket = server.accept()) {
            ProtocolEnvelope handshake = read(socket);
            write(socket, new ProtocolEnvelope(1, "challenge", handshake.serverId(), null, Map.of("challenge", "challenge")));
            read(socket);
            write(socket, new ProtocolEnvelope(1, "login_success", "survival", null, Map.of()));
            write(socket, new ProtocolEnvelope(1, "minecraft_message", "survival", null, Map.of("message", "hello")));
        } catch (Exception exception) {
            throw new RuntimeException(exception);
        }
    }

    private static ProtocolEnvelope read(Socket socket) throws Exception {
        byte[] header = socket.getInputStream().readNBytes(4);
        int size = java.nio.ByteBuffer.wrap(header).getInt();
        return ProtocolEnvelope.fromJson(new String(socket.getInputStream().readNBytes(size), StandardCharsets.UTF_8));
    }

    private static void write(Socket socket, ProtocolEnvelope envelope) throws Exception {
        socket.getOutputStream().write(FrameCodec.encode(envelope.toJson().getBytes(StandardCharsets.UTF_8), 262_144));
        socket.getOutputStream().flush();
    }
}
