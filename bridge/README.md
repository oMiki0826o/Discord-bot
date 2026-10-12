# Minecraft Fabric Bridge

`java_bridge.jar` is the Fabric server-side DMCC bridge. Its complete Gradle project is published in `minecraft-bridge/`, and its SHA-256 is recorded in `SHA256SUMS`.

Build and verify it with Java 21:

```bash
cd bridge/minecraft-bridge
./gradlew --no-daemon test remapJar
cmp build/libs/minecraft-bridge-0.2.0.jar ../java_bridge.jar
```

Use Minecraft 1.21.8, Fabric Loader 0.19.5+ and Java 21+. Copy the jar to the server's `mods/` directory and configure its properties to match the Bot's `settings/dmcc.json` and secret environment variable.
