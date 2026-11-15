# DMCC：Fabric + Velocity 分離安裝

這是兩個同時運作、職責不同的 JAR，不是二選一。

- `minecraft-bridge`（Fabric）：安裝於生存、創造、鏡像三台後端；處理遊戲聊天與事件。
- `dmcc-velocity-bridge`（Velocity）：只安裝於代理；回報真正的代理登入，並轉送 global-whitelist 的加入請求。

## Velocity companion

將 `bridge/velocity-bridge/build/libs/dmcc-velocity-bridge-0.3.0.jar` 放入 Velocity 的 `plugins/`，並在它的資料目錄建立 `bridge.properties`：

```properties
server_id=proxy
gateway_host=127.0.0.1
gateway_port=8765
authentication_secret=replace-with-a-separate-random-secret
bridge_kind=velocity
```

建置時需明確提供與代理相同版本的 Velocity JAR，例如：

```bash
cd bridge/minecraft-bridge
DMCC_VELOCITY_JAR=/path/to/velocity.jar ./gradlew --project-dir ../velocity-bridge clean jar
```

Bot 的 DMCC 設定需有同名、僅作 Gateway peer 的 server；它不需要控制面板或 presentation：

```json
{
  "servers": [
    {"server_id": "proxy", "bridge": {"enabled": true, "peer_kind": "velocity", "secret_env": "DMCC_PROXY_SECRET"}}
  ],
  "proxy_whitelist": {"enabled": true, "server_id": "proxy"},
  "avatar_refresh": {
    "enabled": true,
    "source": "velocity",
    "source_server_id": "proxy",
    "cache_ttl_seconds": 21600
  },
  "private_messages": {"enabled": false}
}
```

`DMCC_PROXY_SECRET` 必須與 `authentication_secret` 相同，但不能重用任一 Fabric server 的 secret。

頭像來源是明確二選一，沒有優先級：一般服設定 `source: "fabric"`，每次 Fabric 的真實 `player_join` 都會重新驗證頭像；有代理則設定 `source: "velocity"`，只接受 Velocity 的 `PostLoginEvent`。生存、創造、鏡像間的後端轉服不會觸發後者。探測順序是 mc-heads、Crafatar，兩者都失敗則保留 webhook 預設頭像。探測為 `avatar_refresh.enabled` 的獨立開關。

代理白名單只接受 Bot 所發出的固定 `globalwhitelist add <Java 玩家名稱>`，不開放 Discord 執行其他 Velocity 指令。既有 global-whitelist 外掛會自行持久化名單；若有人在檔案外部修改 `whitelist.json`，仍需在 Velocity console 執行 `/globalwhitelist reload`。
