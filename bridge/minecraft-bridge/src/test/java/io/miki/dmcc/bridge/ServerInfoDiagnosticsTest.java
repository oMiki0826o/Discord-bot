package io.miki.dmcc.bridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

final class ServerInfoDiagnosticsTest {
    @Test
    void responseKeysMatchTheSharedProtocolContract() throws Exception {
        BridgeRuntime runtime = new BridgeRuntime(() -> new BridgeConnection() {
            @Override public void connect() { }
            @Override public void send(ProtocolEnvelope envelope) { }
            @Override public void awaitDisconnect() { }
            @Override public void close() { }
        }, 1, 1);
        JsonObject contract = JsonParser.parseString(Files.readString(
            Path.of("..", "protocol", "server_info_response.json")
        )).getAsJsonObject();

        Map<String, Object> diagnostics = ServerInfoDiagnostics.from(runtime);

        assertEquals(contract.keySet(), diagnostics.keySet());
    }
}
