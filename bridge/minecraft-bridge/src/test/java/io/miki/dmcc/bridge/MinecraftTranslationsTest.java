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
    void readsModLanguageAssetsWithCustomOverridesAndEnglishFallback() throws Exception {
        Path config = directory.resolve("config");
        Path mod = directory.resolve("mod-root");
        Path assets = mod.resolve("assets").resolve("example").resolve("lang");
        Files.createDirectories(config);
        Files.createDirectories(assets);
        Files.writeString(config.resolve("zh_tw.json"), """
            {"mod.title":"自訂繁中"}
            """);
        Files.writeString(assets.resolve("zh_tw.json"), """
            {"mod.title":"模組繁中", "mod.description":"模組說明"}
            """);
        Files.writeString(assets.resolve("en_us.json"), """
            {"mod.fallback":"Fallback from mod"}
            """);
        MinecraftTranslations translations = MinecraftTranslations.load(
            config, "zh_tw", java.util.List.of(mod)
        );
        assertEquals("自訂繁中", translations.translateKey("mod.title"));
        assertEquals("模組說明", translations.translateKey("mod.description"));
        assertEquals("Fallback from mod", translations.translateKey("mod.fallback"));
    }

    @Test
    void versionSpecificVerifiedMojangCacheLoadsWithoutOverridingCustomLanguage() throws Exception {
        Path languageFolder = directory.resolve("lang");
        Path mojang = languageFolder.resolve("mojang").resolve("1.21.8");
        Files.createDirectories(mojang);
        Files.writeString(mojang.resolve("zh_tw.json"), """
            {"death.attack.arrow":"官方翻譯", "other.key":"Mojang only"}
            """);
        Files.writeString(languageFolder.resolve("zh_tw.json"), """
            {"death.attack.arrow":"管理員覆寫"}
            """);
        var translations = MinecraftTranslations.load(
            languageFolder, "zh_tw", java.util.List.of(), "1.21.8"
        );
        assertEquals("管理員覆寫", translations.translateKey("death.attack.arrow"));
        assertEquals("Mojang only", translations.translateKey("other.key"));
        var wrongVersion = MinecraftTranslations.load(
            languageFolder, "zh_tw", java.util.List.of(), "1.21.9"
        );
        assertEquals("other.key", wrongVersion.translateKey("other.key"));
    }

    @Test
    void selectedDatapacksAreMergedAfterModsBeforeOfficialAssetCache() throws Exception {
        Path folder = directory.resolve("lang");
        Path official = folder.resolve("mojang").resolve("1.21.8");
        Files.createDirectories(official);
        Files.writeString(official.resolve("zh_tw.json"), """
            {"test.one":"Official", "test.two":"Official 2"}
            """);
        var packs = new MinecraftPackTranslations.Snapshot(
            java.util.Map.of("test.one", "Selected data pack"),
            java.util.Map.of()
        );
        var catalog = MinecraftTranslations.load(folder, "zh_tw", java.util.List.of(),
            "1.21.8", packs);
        assertEquals("Selected data pack", catalog.translateKey("test.one"));
        assertEquals("Official 2", catalog.translateKey("test.two"));
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
