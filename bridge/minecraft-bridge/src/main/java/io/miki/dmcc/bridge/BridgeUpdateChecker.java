package io.miki.dmcc.bridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/** Optional, bounded update lookup for this project's own public releases. */
final class BridgeUpdateChecker {
    private static final URI RELEASE = URI.create(
        "https://api.github.com/repos/oMiki0826o/Discord-bot/releases/latest");
    private BridgeUpdateChecker() { }

    static String latestRelease() throws IOException {
        HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .followRedirects(HttpClient.Redirect.NEVER).build();
        HttpRequest request = HttpRequest.newBuilder(RELEASE)
            .timeout(Duration.ofSeconds(8))
            .header("Accept", "application/vnd.github+json")
            .header("User-Agent", "dmcc-minecraft-bridge")
            .GET().build();
        try {
            HttpResponse<InputStream> response = client.send(request, HttpResponse.BodyHandlers.ofInputStream());
            try (InputStream in = response.body()) {
                if (response.statusCode() != 200) {
                    throw new IOException("release lookup unavailable (HTTP " + response.statusCode() + ")");
                }
                byte[] bytes = in.readNBytes(16_385);
                if (bytes.length > 16_384) throw new IOException("release metadata too large");
                return parseRelease(new String(bytes, java.nio.charset.StandardCharsets.UTF_8));
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IOException("release lookup interrupted", interrupted);
        }
    }

    static String parseRelease(String json) throws IOException {
        try {
            JsonObject root = JsonParser.parseString(json).getAsJsonObject();
            if (!root.has("tag_name") || !root.get("tag_name").isJsonPrimitive()) {
                throw new IOException("release metadata has no tag");
            }
            String tag = root.get("tag_name").getAsString();
            if (!tag.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,63}")) {
                throw new IOException("release tag is invalid");
            }
            return "Latest DMCC release: " + tag
                + " (github.com/oMiki0826o/Discord-bot/releases)";
        } catch (RuntimeException invalid) {
            throw new IOException("release metadata was malformed", invalid);
        }
    }
}
