# DMCC / Minecraft Bridge

`dmcc` connects Discord with a Minecraft 1.21.8 Fabric server through a localhost-only Protocol v1 gateway. Put `bridge/java_bridge.jar` in the Minecraft server `mods/` directory, then configure a matching `server_id`, port, and secret environment variable in `settings/dmcc.json`.

The gateway only listens on `127.0.0.1`; keep bridge secrets in `.env`, never in JSON. Protocol frames are limited to 262144 bytes on both sides. `local_tmux`, Pterodactyl, and MCSManager controls are configured as control providers; use the least privileged panel credential possible.

Before production, validate HMAC authentication, relay, console requests, and each power action against a non-critical server.
