/* HMAC-SHA256 helper shared by the Bridge authentication state machine. */
package io.miki.dmcc.bridge;

import java.nio.charset.StandardCharsets;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Produces the DMCC Protocol v1 challenge response. */
public final class Authentication {
    private Authentication() {
    }

    public static String createResponse(String challenge, String secret) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return toHex(mac.doFinal(challenge.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception exception) {
            throw new ProtocolException("unable to calculate authentication response", exception);
        }
    }

    private static String toHex(byte[] bytes) {
        StringBuilder output = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            output.append(String.format("%02x", value));
        }
        return output.toString();
    }
}
