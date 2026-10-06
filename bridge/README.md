# Minecraft Fabric Bridge

`java_bridge.jar` is the Fabric server-side DMCC bridge. It is built from the local `test_mod/minecraft-bridge` source with `./gradlew --no-daemon test remapJar` and its SHA-256 is recorded in `SHA256SUMS`.

Use Minecraft 1.21.8, Fabric Loader 0.19.5+ and Java 21+. Copy the jar to the server's `mods/` directory and configure its properties to match the Bot's `settings/dmcc.json` and secret environment variable.
