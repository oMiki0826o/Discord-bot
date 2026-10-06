# DMCC / Minecraft Bridge

`dmcc` connects Discord with a Minecraft 1.21.8 Fabric server through a localhost-only Protocol v1 gateway. Put `bridge/java_bridge.jar` in the Minecraft server `mods/` directory, then configure a matching `server_id`, port, and secret environment variable in `settings/dmcc.json`.

The gateway only listens on `127.0.0.1`; keep bridge secrets in `.env`, never in JSON. Protocol frames are limited to 262144 bytes on both sides. `local_tmux`, Pterodactyl, and MCSManager controls are configured as control providers; use the least privileged panel credential possible.

Before production, validate HMAC authentication, relay, console requests, and each power action against a non-critical server.

## 最小 Linux 範例

`.env`：

```env
DMCC_SURVIVAL_SECRET=請換成一段長且隨機的密碼
```

`settings/dmcc.json`：

```json
{
  "gateway": {"host": "127.0.0.1", "port": 8765},
  "mode": "standalone",
  "providers": {
    "control": [{
      "provider_id": "survival-local",
      "type": "local_tmux",
      "options": {
        "server_dir": "/srv/minecraft/survival",
        "session_name": "mc-survival",
        "start_argv": ["java", "-Xms2G", "-Xmx4G", "-jar", "server.jar", "nogui"]
      }
    }],
    "backup": []
  },
  "servers": [{
    "server_id": "survival",
    "bridge": {"enabled": true, "secret_env": "DMCC_SURVIVAL_SECRET"},
    "control_provider": "survival-local",
    "control_target": "mc-survival",
    "identity_enabled": true,
    "allow_kill": false
  }],
  "permissions": {"user_mappings": [], "role_mappings": []}
}
```

Bridge 設定位置為 `<Minecraft資料夾>/config/minecraft-bridge.properties`；`server_id`、port 和 `authentication_secret` 必須與上方設定一致。啟動後可用 `$dmcc server-status survival` 查詢，並由 Owner 使用 `$dmcc power survival start|stop|restart` 控制。不同主機請勿把 gateway 改成公開 IP。
