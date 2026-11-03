# Minecraft Fabric Bridge

`java_bridge.jar` is generated from the Fabric sources by the CI `bridge` job; the checked-in Git repository intentionally contains no prebuilt JAR. The release ZIP and workflow artifact include the newly built JAR plus `SHA256SUMS`.

Build and verify it with Java 21:

```bash
cd bridge/minecraft-bridge
./gradlew --no-daemon test remapJar
cp build/libs/minecraft-bridge-0.2.4.jar ../java_bridge.jar
```

Use Minecraft 1.21.8, Fabric Loader 0.19.5+, Fabric API and Java 21+. Copy both Fabric API and this jar to the server's `mods/` directory, then configure its properties to match the Bot's `settings/dmcc.json` and secret environment variable.
