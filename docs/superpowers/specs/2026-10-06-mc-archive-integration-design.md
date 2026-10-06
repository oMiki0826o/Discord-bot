# Minecraft Archive Integration Design

## Goal

Selectively adopt the validated archive's Minecraft operational and security improvements while preserving the current Discord Bot architecture, current AI changes, and the Fabric bridge JAR built from the local source tree.

## Scope

The integration covers `bot.mod.dmcc`, `bot.mod.mc_backup`, their regression tests, deployment documentation, and a distributable Bridge artifact. It does not replace AI code, broad application modules, or dependency constraints solely because the archive has newer versions.

## Selected Improvements

### DMCC gateway and controls

- Enforce the configured frame limit on both outbound and inbound protocol frames.
- Treat request responses that arrive after a timeout as stale and ignore them safely.
- Reject non-loopback gateway hosts, invalid ports, plaintext or empty bridge secrets, and string values where strict booleans are required.
- Add the configured `local_tmux` control provider, validate its target configuration, and run the configured command through fixed argv with the Minecraft server directory as its working directory.
- Use the verified MCSManager status and action endpoint contract, including query-parameter API key authentication.
- Disable Discord mentions for Minecraft-originated relay messages.

### Backup and restore safety

- Make shell resources executable and ensure start/stop logic runs in the configured server directory and waits for the tmux session to exit.
- Use atomic JSON persistence with fsync and quarantine malformed state documents.
- Validate backup identifiers, metadata booleans, tar members, and restore extraction boundaries; reject unsafe links and paths.

### Delivery documentation

- Add focused DMCC, backup, and Bridge setup documentation.
- Publish the locally built `java_bridge.jar` with its SHA-256 checksum. The archive's jar is reference material only because it has a different checksum.

## Constraints

- Do not add plaintext secrets to tracked files.
- Do not alter unrelated AI code or dependency versions without a separate compatibility change.
- Keep the Gateway bound only to `127.0.0.1`.
- Keep the Protocol v1 frame ceiling at `262144` bytes on both Python and Java sides.
- Preserve compatibility with Python 3.11, the current Bot module loader, and Fabric bridge source currently in `test_mod/minecraft-bridge`.

## Verification

- Add focused regression tests before each adopted behavior.
- Run the complete Discord Bot test suite.
- Build and test the Fabric bridge with `./gradlew --no-daemon test remapJar`.
- Perform a limited Discord live smoke test using the existing test channel only after automated checks pass.
