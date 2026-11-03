# DMCC / Minecraft Bridge

`dmcc` connects Discord to Minecraft **1.21.8 or 1.21.9** Fabric servers through a localhost-only Protocol v1 gateway. Obtain the matching *CI-built* Bridge JAR from the Actions artifact or release ZIP and put it in the server `mods/` directory, then configure a matching `server_id`, port, and secret environment variable in `settings/dmcc.json`.

The gateway only listens on `127.0.0.1`; keep bridge secrets in `.env`, never in JSON. Protocol frames are limited to 262144 bytes on both sides. `local_tmux`, Pterodactyl, and MCSManager controls are configured as control providers; use the least privileged panel credential possible.

Java Bridge 的 `read_timeout_millis` 應至少設為 Python Gateway
`heartbeat_interval_seconds × 3000`，保留兩個 heartbeat interval 的延遲裕度。
`/dmcc server-info` 會顯示 required/event queue 深度、容量、丟棄事件與最後傳送錯誤。

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

Bridge 需要 Fabric API，設定位置為 `<Minecraft資料夾>/config/minecraft-bridge.properties`；`server_id`、port 和 `authentication_secret` 必須與上方設定一致。啟動後可用 `$dmcc server-status survival` 查詢，並由 Owner 使用 `$dmcc power survival start|stop|restart` 控制。不同主機請勿把 gateway 改成公開 IP。

Bridge 將必要請求回覆與一般玩家事件分開排隊。一般事件滿載時可以丟棄並累計診斷數字，必要回覆保有獨立容量；關服時會在有限期限內送出 `server_stopping`，不會無期限阻塞 Minecraft 關閉流程。`latest.log` 僅在背景讀取有限檔尾。


## Discord 訊息呈現：Bot / Webhook

Bridge 以 `settings/dmcc.json` 的 `presentation` 區塊控制輸出。沒有設定時維持原有 Bot 訊息與 `$dmcc map` 頻道對應，不需要遷移資料；以下為單台伺服器的**示意設定片段**，需合併進既有 JSON 物件，而非直接取代完整檔案：

```json
{
  "presentation": {
    "servers": {
      "survival": {
        "label": "生存服",
        "chat": {
          "mode": "webhook",
          "webhook_url_env": "DMCC_CHAT_WEBHOOK",
          "username": "[{server}] {player}"
        },
        "events": {
          "mode": "webhook",
          "webhook_url_env": "DMCC_EVENTS_WEBHOOK",
          "username": "KunlunSMP🌸"
        },
        "templates": {
          "player_join": "**{player} 加入了 {server}**",
          "player_quit": "**{player} 離開了 {server}**"
        },
        "event_routes": {
          "player_death": {"mode": "bot", "channel_id": "123456789012345678"}
        },
        "disabled_events": []
      }
    }
  }
}
```

請在啟動 Bot 的環境中設定 `DMCC_CHAT_WEBHOOK` 與 `DMCC_EVENTS_WEBHOOK`，值為 Discord 實際產生的 HTTPS Webhook URL。**URL 包含私密 Token，不可提交至 GitHub，也不要直接填在 JSON 設定中。** 請先在 Discord 頻道建立對應 Webhook 並確認權限。

- `chat` 處理玩家聊天；`events` 處理加入、退出、死亡、進度、模式切換和伺服器啟停。各自可設 `mode: "bot"` 或 `mode: "webhook"`，這就是混合模式。
- `chat.username` 和 `events.username` 僅對 Webhook 模式有效，支援 `{server}`、`{player}` 等安全佔位符；玩家頭像會根據 Minecraft UUID 組成公開頭像服務 URL，沒有 UUID 時使用 Discord 預設頭像。
- `templates` 以事件名稱為鍵，自訂內容；支援 `{server}`、`{player}`、`{message}`、`{death_message}`、`{game_mode}`、`{title}`、`{label}`。可使用 `player_chat` 自訂聊天文字。
- `event_channels` 可覆寫 Bot 事件頻道；Webhook 依自己的 URL 決定實際投遞頻道。若需要某個事件使用不同 Webhook，應在 `event_routes` 為該事件設定獨立 `mode`、`webhook_url_env` 和 `channel_id`。不可用 `event_channels` 重新導向 Webhook。
- `chat.channel_id`、`events.channel_id`、`event_routes.*.channel_id` 可以覆寫預設輸出頻道。Discord → Minecraft 仍透過現有 `$dmcc map` 映射，不會因單向輸出改動而無意重新路由。
- Webhook API 失敗時，會改由 Bot 發送且保留玩家名稱；訊息的 Mention 皆停用自動通知。這種備援只在 Bot 有該頻道權限並能取得頻道物件時生效。

### Deployment notes (English)

Presentation is opt-in under `settings/dmcc.json → presentation.servers.<server_id>`. The existing Bot channel mapping remains unchanged if no profile is configured. Each of `chat`, `events`, and optional `event_routes` supports independent Bot or Webhook delivery. Provide Webhook URLs only through the environment variables named by `webhook_url_env`, never through committed JSON. A Webhook URL controls its destination channel; changing `channel_id` alone cannot redirect it. Failed Webhook sends fall back to the Bot with player attribution preserved, and all automatic mentions are disabled. Only Fabric Minecraft 1.21.8 is currently listed as a tested build target.

## 監控與模組更新（選用）

新版 Bridge 每 300 個伺服器 Tick 傳送一次 `server_metrics`（MSPT、估算 TPS、在線玩家與玩家上限）。Python Gateway 在**驗證 HMAC 後**才會接受，並在 180 秒沒有新資料時將指標視為不可用，而非假裝伺服器正常。

在既有 `settings/dmcc.json` 最外層合併下列區塊（只是一部分，**不要覆蓋既有伺服器與管理員設定**）：

```json
{
  "monitoring": {
    "enabled": true,
    "presence": false,
    "interval_seconds": 60,
    "alert_duration_seconds": 60,
    "alert_cooldown_seconds": 600,
    "channel_cooldown_seconds": 600,
    "servers": {
      "survival": {
        "label": "生存服",
        "alert_channel_id": "123456789012345678",
        "topic_channel_id": "123456789012345679",
        "status_voice_channel_id": "123456789012345680",
        "mspt_threshold": 45,
        "mspt_recovery": 40
      }
    }
  },
  "mod_updates": {
    "enabled": true,
    "interval_seconds": 3600,
    "servers": {
      "survival": {
        "channel_id": "123456789012345678",
        "minecraft_version": "1.21.8",
        "projects": {"lithium": "gvQqBUqZ"}
      }
    }
  }
}
```

- **監控**：指標連續高於門檻至少 60 秒才發警告；回復到較低門檻後才發復原通知。Discord 通知發送失敗不會阻塞 Minecraft Tick。指標逾時不會錯誤地推斷「已復原」。
- **頻道狀態**：`topic_channel_id` 編輯文字頻道 Topic，`status_voice_channel_id` 編輯語音頻道名稱（**不會連接語音通話**）。Bot 需有「管理頻道」權限；為遵守 Discord API 使用速率限制，變更至少間隔 600 秒。
- **Presence**：`presence: false` 預設不覆寫全站 Bot 狀態。啟用後可顯示 Minecraft 在線人數；停用 DMCC 時解除自身狀態覆寫，並尊重其他模組持有的狀態控制權。若顯示 `metrics unavailable`，代表未收到新資料。
- **Modrinth 更新通知**：只查詢明確填入 `projects` 的 Fabric 模組 ID → Modrinth Project ID，不會自動上傳模組檔案或安裝更新。實際已安裝版本來自 Bridge 啟動時回報的 Fabric Loader 清單；只有在 Modrinth 明確列出此版本、且新版本也支援所設定 Minecraft 版本與 Fabric Loader，才會提示新版本。未知版本與手動魔改版不冒然判定「可更新」。請依實際 Modrinth 專案填入 ID。
- **權限與風險**：此功能不授予遊戲操作權限；請勿把內網 Gateway 改為公開監聽。Topic／頻道名稱／Presence 均由 Bot 修改，請避免同時讓其他機器人頻繁管理相同頻道，以免互相覆寫。
- **多伺服器**：每個 `server_id` 可獨立配置監控與更新；每台 Java Bridge 使用該版本相符的 Fabric Mod JAR。

## Monitoring and mod updates (English)

Monitoring is **disabled by default** and receives authenticated Bridge telemetry. Optional settings update a text-channel topic and a voice-channel name, alert only on sustained MSPT degradation, and (when explicitly enabled) set a reversible Minecraft Presence override. Permissions to manage channels are required. Monitoring edits are rate-limited to one change per 600 seconds per field, with stale metrics treated as unknown. `mod_updates` is also opt-in; it consults Modrinth only for explicitly mapped Fabric mods and announces *known compatible* updates, without downloading or installing anything. Match the server's exact Minecraft version to its CI-built JAR (1.21.8 or 1.21.9). Full end-to-end verification on your deployed Discord and Minecraft servers must be performed before production rollout.
