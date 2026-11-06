package io.miki.dmcc.bridge;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import net.minecraft.network.chat.Component;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class MinecraftTranslationsTest {
    @TempDir Path directory;

    @Test
    void translatesNestedVanillaComponentsWithLocaleFallback() throws Exception {
        Path folder = directory.resolve("lang");
        Files.createDirectories(folder);
        Files.writeString(folder.resolve("zh_tw.json"), """
            {"death.attack.arrow":"%1$s 被 %2$s 射中了",
             "chat.type.text":"<%s> %s",
             "advancements.custom.title":"自訂進度"}
            """);
        Files.writeString(folder.resolve("en_us.json"), """
            {"death.attack.arrow":"%1$s was shot by %2$s",
             "test.fallback":"English fallback: %s"}
            """);
        MinecraftTranslations translations = MinecraftTranslations.load(folder, "zh_tw");
        assertEquals("Steve 被 Alex 射中了", translations.translateKey(
            "death.attack.arrow", "Steve", "Alex"));
        assertEquals("English fallback: Hello", translations.translateKey(
            "test.fallback", "Hello"));
        assertEquals("自訂進度", translations.translate(Component.translatable(
            "advancements.custom.title")));
        assertEquals("unknown.translation", translations.translateKey("unknown.translation"));
    }

    @Test
    void missingAndMalformedCatalogsNeverCrashEventRendering() throws Exception {
        Path folder = directory.resolve("lang");
        Files.createDirectories(folder);
        Files.writeString(folder.resolve("zh_tw.json"), "{malformed");
        MinecraftTranslations translations = MinecraftTranslations.load(folder, "zh_tw");
        assertEquals("Hello", translations.translate(Component.literal("Hello")));
        assertEquals("unknown.key", translations.translateKey("unknown.key"));
    }

    @Test
    void formattingIsBoundedAndDoesNotExecuteUnexpectedPlaceholders() throws Exception {
        Path folder = directory.resolve("lang");
        Files.createDirectories(folder);
        Files.writeString(folder.resolve("en_us.json"), """
            {"test.percent":"100%% %1$s", "test.number":"%2$s then %1$s",
             "test.invalid":"%9$s"}
            """);
        MinecraftTranslations translations = MinecraftTranslations.load(folder, "en_us");
        assertEquals("100% done", translations.translateKey("test.percent", "done"));
        assertEquals("b then a", translations.translateKey("test.number", "a", "b"));
        assertEquals("%9$s", translations.translateKey("test.invalid", "x"));
        assertTrue(translations.translateKey("test.percent", "X".repeat(3000)).length() <= 1800);
    }
}
