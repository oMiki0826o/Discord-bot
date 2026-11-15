package io.miki.dmcc.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.AtomicMoveNotSupportedException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Properties;
import java.util.Set;

/**
 * Optional background-only official Minecraft language cache updater.
 * Never runs on the Minecraft tick thread; no arbitrary redirects or hosts.
 */
final class OfficialLanguageUpdater {
    private static final URI MANIFEST = URI.create(
        "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json");
    private static final Set<String> META = Set.of(
        "piston-meta.mojang.com", "launchermeta.mojang.com");
    private static final Set<String> ASSET = Set.of("resources.download.minecraft.net");
    private static final int MAX_ASSET = 4_000_000;
    private final HttpClient client;

    OfficialLanguageUpdater() {
        client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(8))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    static boolean enabled(Path configFile) {
        Properties properties = new Properties();
        try (var reader = Files.newBufferedReader(configFile)) {
            properties.load(reader);
            return "true".equals(properties.getProperty("language_auto_download", "false"));
        } catch (IOException invalid) {
            return false;
        }
    }

    boolean update(Path languageDirectory, String version, String locale) throws IOException {
        if (languageDirectory == null || version == null || locale == null
            || !version.matches("[0-9]{1,3}\\.[0-9]{1,3}(\\.[0-9]{1,3})?")
            || !locale.matches("[a-z]{2}_[a-z]{2}")) {
            throw new IOException("unsafe language cache version or locale");
        }
        if ("en_us".equals(locale)) return false;
        JsonObject manifest = json(fetch(MANIFEST, META, 8_000_000));
        JsonObject versionInfo = null;
        for (JsonElement item : manifest.getAsJsonArray("versions")) {
            JsonObject row = item.getAsJsonObject();
            if (version.equals(row.get("id").getAsString())) {
                versionInfo = row;
                break;
            }
        }
        if (versionInfo == null) throw new IOException("Minecraft version unavailable");
        byte[] metadata = fetch(URI.create(versionInfo.get("url").getAsString()), META, 4_000_000);
        if (versionInfo.has("sha1")) checkSha1(metadata, versionInfo.get("sha1").getAsString());
        JsonObject indexInfo = json(metadata).getAsJsonObject("assetIndex");
        if (indexInfo == null) throw new IOException("missing Minecraft asset index");
        byte[] indexBytes = fetch(URI.create(indexInfo.get("url").getAsString()), META, 40_000_000);
        checkSha1(indexBytes, indexInfo.get("sha1").getAsString());
        JsonObject objects = json(indexBytes).getAsJsonObject("objects");
        if (objects == null) throw new IOException("missing Minecraft assets");
        JsonObject entry = objects.getAsJsonObject("minecraft/lang/" + locale + ".json");
        if (entry == null) throw new IOException("official Minecraft locale absent");
        String sha1 = entry.get("hash").getAsString();
        if (!sha1.matches("[0-9a-f]{40}")) throw new IOException("invalid Mojang content hash");
        byte[] asset = fetch(URI.create(
            "https://resources.download.minecraft.net/" + sha1.substring(0, 2) + "/" + sha1
        ), ASSET, MAX_ASSET);
        checkSha1(asset, sha1);
        if (entry.has("size") && entry.get("size").getAsLong() != asset.length) {
            throw new IOException("official Minecraft language size mismatch");
        }
        JsonObject translations = json(asset);
        if (translations.size() > 50_000) throw new IOException("too many language keys");

        Path folder = languageDirectory.resolve("mojang").resolve(version);
        Path cursor = languageDirectory;
        for (String part : new String[]{"mojang", version}) {
            if (Files.isSymbolicLink(cursor)) throw new IOException("unsafe language directory");
            cursor = cursor.resolve(part);
        }
        if (Files.isSymbolicLink(cursor)) throw new IOException("unsafe language directory");
        Files.createDirectories(folder);
        Path target = folder.resolve(locale + ".json");
        if (Files.isSymbolicLink(target)) throw new IOException("unsafe language cache file");
        if (Files.isRegularFile(target) && Files.size(target) == asset.length) {
            byte[] old = Files.readAllBytes(target);
            if (MessageDigest.isEqual(old, asset)) return false;
        }
        Path temp = Files.createTempFile(folder, ".mojang-language-", ".tmp");
        try {
            Files.write(temp, asset);
            try {
                Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException unsupported) {
                Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } finally {
            Files.deleteIfExists(temp);
        }
        return true;
    }

    private byte[] fetch(URI uri, Set<String> permitted, int max) throws IOException {
        if (!"https".equals(uri.getScheme()) || !permitted.contains(uri.getHost())
            || uri.getUserInfo() != null || (uri.getPort() != -1 && uri.getPort() != 443)
            || uri.getFragment() != null) {
            throw new IOException("non-official Mojang download refused");
        }
        HttpRequest request = HttpRequest.newBuilder(uri)
            .timeout(Duration.ofSeconds(18)).GET().build();
        try {
            HttpResponse<InputStream> response = client.send(
                request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() != 200) {
                response.body().close();
                throw new IOException("official language HTTP " + response.statusCode());
            }
            try (InputStream input = response.body()) {
                byte[] raw = input.readNBytes(max + 1);
                if (raw.length < 2 || raw.length > max) {
                    throw new IOException("official language download size exceeded");
                }
                return raw;
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IOException("language download interrupted", interrupted);
        }
    }

    private static JsonObject json(byte[] content) throws IOException {
        try {
            JsonElement object = JsonParser.parseString(
                new String(content, java.nio.charset.StandardCharsets.UTF_8));
            if (!object.isJsonObject()) throw new IOException("invalid official language JSON");
            return object.getAsJsonObject();
        } catch (RuntimeException invalid) {
            throw new IOException("malformed official Minecraft language resource", invalid);
        }
    }

    private static void checkSha1(byte[] data, String expected) throws IOException {
        if (!expected.matches("[0-9a-f]{40}")) throw new IOException("invalid official SHA-1");
        try {
            String calculated = HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-1").digest(data));
            if (!expected.equals(calculated)) throw new IOException("official SHA-1 mismatch");
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IOException("SHA-1 algorithm unavailable", unavailable);
        }
    }
}
