# Minecraft Fabric Bridge

`java_bridge.jar` is generated from the Fabric sources by the CI `bridge` job; the checked-in Git repository intentionally contains no prebuilt JAR. The release ZIP and workflow artifact include the newly built JAR plus `SHA256SUMS`.

Build and verify it with Java 21:

```bash
cd bridge/minecraft-bridge
./gradlew --no-daemon test remapJar
cp build/libs/minecraft-bridge-0.2.4.jar ../java_bridge.jar
```

Use the **version-matched** JAR produced by CI: `bridge/java_bridge.jar` for Minecraft **1.21.8**, and `bridge/versions/1.21.9/java_bridge.jar` for **1.21.9**, with the matching Fabric API, Fabric Loader and Java 21+. The artifact includes per-version `SHA256SUMS`. Copy the JAR and Fabric API into the Minecraft server's `mods/` folder, then configure its properties to match the Bot's `settings/dmcc.json` and secret environment variable.

Each matrix build expands `fabric.mod.json` with an exact matching Minecraft version. Run locally, from `bridge/minecraft-bridge`:

```sh
./gradlew --no-daemon -Pminecraft_version=1.21.9 -Pfabric_api_version=0.134.0+1.21.9 test remapJar
```

Other Minecraft versions require an independently verified build and are **not claimed supported**. Source changes require a new CI build; do not deploy stale JARs from repository history.


Additional feature branch support: Fabric's public `COMMAND_MESSAGE` event is forwarded as `server_broadcast`. Events explicitly directed to private recipients are not intentionally captured. The Python Bot can optionally poll bounded `latest.log` excerpts and forward redacted deltas to administrator-only channels. Both features are controlled by the DMCC Bot configuration; actual server integration testing remains necessary.
