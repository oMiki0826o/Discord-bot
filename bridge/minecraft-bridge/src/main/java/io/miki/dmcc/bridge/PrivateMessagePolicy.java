package io.miki.dmcc.bridge;

import java.util.Locale;
import java.util.regex.Pattern;

/** Strict vanilla /msg, /tell, /w classification: all-player selectors are public only without filters. */
public final class PrivateMessagePolicy {
    private static final Pattern VANILLA = Pattern.compile(
        "^/?(?:msg|tell|w)\\s+\\S+\\s+\\S[\\s\\S]*$", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern ALL_PLAYERS = Pattern.compile(
        "^/?(?:msg|tell|w)\\s+@a\\s+\\S[\\s\\S]*$", Pattern.CASE_INSENSITIVE
    );

    private PrivateMessagePolicy() { }

    public static boolean isVanillaAlias(String input) {
        return input != null && input.length() <= 4096 && VANILLA.matcher(input.strip()).matches();
    }

    public static boolean isAllPlayersMessage(String input) {
        return isVanillaAlias(input) && ALL_PLAYERS.matcher(input.strip()).matches();
    }
}
