/* Immutable JSON envelope for DMCC Protocol v1. */
package io.miki.dmcc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonNull;
import com.google.gson.JsonParser;
import com.google.gson.reflect.TypeToken;
import java.lang.reflect.Type;
import java.util.Map;

/** Defines the exact JSON document exchanged after FrameCodec has reconstructed a frame. */
public record ProtocolEnvelope(
    int protocolVersion,
    String type,
    String serverId,
    String requestId,
    Map<String, Object> data
) {
    private static final Gson GSON = new Gson();
    private static final Type DATA_TYPE = new TypeToken<Map<String, Object>>() { }.getType();

    public ProtocolEnvelope {
        if (protocolVersion != 1 || type == null || type.isBlank() || serverId == null || serverId.isBlank() || data == null) {
            throw new ProtocolException("invalid Protocol v1 envelope");
        }
        data = Map.copyOf(data);
    }

    public String toJson() {
        JsonObject object = new JsonObject();
        object.addProperty("protocol_version", protocolVersion);
        object.addProperty("type", type);
        object.addProperty("server_id", serverId);
        object.add("request_id", requestId == null ? JsonNull.INSTANCE : GSON.toJsonTree(requestId));
        object.add("data", GSON.toJsonTree(data));
        return object.toString();
    }

    public static ProtocolEnvelope fromJson(String json) {
        try {
            JsonObject object = JsonParser.parseString(json).getAsJsonObject();
            if (!object.has("protocol_version") || !object.has("type") || !object.has("server_id")
                || !object.has("request_id") || !object.has("data")) {
                throw new ProtocolException("envelope has missing fields");
            }
            return new ProtocolEnvelope(
                object.get("protocol_version").getAsInt(),
                object.get("type").getAsString(),
                object.get("server_id").getAsString(),
                object.get("request_id").isJsonNull() ? null : object.get("request_id").getAsString(),
                GSON.fromJson(object.get("data"), DATA_TYPE)
            );
        } catch (ProtocolException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ProtocolException("invalid JSON envelope", exception);
        }
    }
}
