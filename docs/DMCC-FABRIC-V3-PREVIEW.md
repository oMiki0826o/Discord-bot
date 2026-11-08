# Fabric DMCC v3 功能預覽分支（初版）

> **狀態：開發預覽／自行實機驗證；非正式發布。** 使用 `feat/dmcc-v3-parity` 分支，**不合併** `main`。NeoForge 暫不新增功能。

## 架構

```text
Discord API / Webhook
   ├─ Discord Cog（指令、編輯／刪除／回應）
   ├─ V3FeatureConfig（功能矩陣、來源事件、模板與 alias）
   ├─ MessageFormat / RichText / V3Templates / V3Minecraft（雙向解析）
   └─ Python DMCC Gateway（已驗證 HMAC，訊息佇列，事件路由）
                       │ TCP Protocol v1
                 Fabric Bridge 1.21.8 / 1.21.9
   ├─ Minecraft Native Message / RichText
   ├─ 死亡、進度、遊戲模式、加入退出與指令事件
   ├─ MinecraftTranslations + 選取中的 Client Resources datapacks
   ├─ 玩家連結、OP 所有權名冊、通知
   └─ Minecraft Server
```

### 分層與負責檔案

| 範圍 | 實作位置 | 初版狀態 |
|---|---|---|
| 輸入輸出與 Gateway | `gateway/`, `protocol/`, `extension.py` | 沿用既有實作 |
| 訊息解析功能矩陣 | `services/v3_features.py` | 初版可配置／預設關閉 |
| Minecraft → Discord 格式轉換 | `services/v3_minecraft.py` | alias、顯示型提及、Emoji |
| Discord → Minecraft | `services/message_format.py`, `rich_text.py`, `discord_relay.py` | 舊版相容＋可選功能矩陣 |
| 自訂富文字模板 | `services/v3_templates.py` | 受限片段、顏色與變數插入 |
| Discord 事件模板 | `services/presentation.py` | Bot/Webhook／欄位擴充 |
| Minecraft 原生訊息覆寫 | `NativeMessageFormatter.java`, `NativeRichText.java` | 初版 Markdown、連結；必須開啟覆寫選項 |
| Mojang 語言資源 | `tools/fetch_minecraft_languages.py` | 管理員主動下載、SHA-1 驗證、版本快取 |
| Mod 與資料包語言資源 | `MinecraftTranslations.java`, `MinecraftPackTranslations.java` | 讀取已選取 Client Resources 資料包，重載時更新 |
| 熱重載 | `dmcc preview-refresh` | 僅 parser、模板、顯示設定，Gateway 不重啟 |
| 權限和管理 | `OpSyncService`、`ManagedOpLedger`、指令 Cog | 沿用，預設安全設定 |
| 執行狀態／監控 | `monitoring`, `stats`, `console_stream`, `event_queue` | 沿用 |
| 壓力／網路整合 | `tests/test_dmcc_gateway_integration.py`、`tools/fabric_real_gateway_smoke.py` | 已提供測試，需實機再次核對 |

### 上游 DMCC v3 功能矩陣

| 功能類型 | 初版介面／處理方式 | 注意事項 |
|---|---|---|
| Discord 文字、Markdown、超連結、ANSI | `v3_features.message_parsing.discord_to_minecraft` | 安全 subset；不接受 RunCommand |
| Discord 附件、貼圖、Embed、投票、元件 | metadata 摘要與選項 | 複雜互動式元件不是逐像素或互動等價 |
| Discord 提及、角色、時間戳、自訂 Emoji | bounded formatter、user/role mentions | `@everyone` 不直接廣播；角色通知 opt-in |
| Discord 回覆、編輯、刪除、表情反應 | `discord_relay.py` | 使用來源訊息 ID、避免跨服混淆 |
| MC → Discord 玩家／伺服器事件 | `MinecraftDiscordRelayService` | 事件路由與 Bot/Webhook 模板 |
| MC → Discord custom Emoji/提及 | `v3_minecraft.py`、明確 alias 映射 | Discord 實際 ping 受 AllowedMentions 限制 |
| MC → MC Markdown、連結、Unicode | `NativeRichText.java` | 仍是初版 parser；需真實 Minecraft 客戶端驗證 |
| 原生簽章聊天覆寫 | `overwrite_native_messages` | **預設關閉**；會改變簽章與檢舉語意 |
| `/say`, `/me`, `/tellraw @a` | 公開廣播事件＋收件者共識檢查 | 私人訊息不轉公開 Discord |
| `/msg`, `/tell`, `/w` | source_events schema 預留 `msg` | **公開頻道禁用**；未建立私訊對私訊傳輸 |
| 權限綁定、OP 同步、freeze/kick | 綁定與權限服務 | 權限與安全行為不照搬上游不安全預設 |
| TPS/MSPT、Console、更新、狀態 | 原有獨立服務 | 啟用需要在實際設定中逐項配置 |
| 語言官方／Mod／選中資料包 | 語言快取與 pack snapshot | 自動網路下載仍需外部排程；伺服器不在主 Tick 下載 |
| 設定熱重載 | `dmcc preview-refresh` | 只更新 display/parser，底層連線與權限仍需標準 reload |

## 立即測試

1. 將 `docs/examples/dmcc-v3-preview.json` 的 `v3_features` 合併至 **既有** `data/settings/dmcc.json`；不要用範例覆蓋 Gateway secrets、Server ID 或路由。
2. 確認 `rich_chat=true`，並依需要在 Fabric 的 `config/minecraft-bridge.properties` 設定 `translation_locale=zh_tw` 以及 `overwrite_native_messages`。後者只建議在隔離測試伺服器開啟。
3. 如需官方語系，執行 `python3 -m tools.fetch_minecraft_languages --minecraft-version 1.21.8 --locale zh_tw --directory <伺服器>/config/minecraft-bridge/lang`。
4. Discord 管理員透過 `dmcc preview-refresh`（Bot 前綴指令）重讀 V3 parser／模板，不必重啟 Gateway。不能用它刷新授權、端口、OP 或所有模組狀態。
5. 使用 JAR 和 Bot **同一分支版本** 測試，觀察一般聊天、編輯、反應、`/say`、`/tellraw`、斷線及重連。

### 請優先回報的問題

- Fabric 1.21.8 和 1.21.9 有無 Mixin 失敗或不同資源 API。
- 資料包或 Mod 語言檔重複鍵值時的覆寫順序。
- 原生訊息覆寫與其他聊天 Mod 的互動以及重複訊息。
- Markdown 與 Emoji 在遊戲內的真實 Hover／點擊／色彩。
- Discord Bot/Webhook Rate Limit、頻道授權、允許提及、Message Content Intent。
- 伺服器重啟後權限資料與負載行為。

## 開發與驗收邊界

這份是**所有主要能力有位置、有設定、有初步程式路徑的架構版**，不是 DMCC v3 上游 100% 行為對等證明。未完成的細節與真實 Discord／客戶端交互由實機測試暴露後再修復。此檔為公開的使用者功能說明，**私人協作文件與 Superpowers 工作筆記不得提交到 Git**。


## 第二批初版功能：實際路由、私訊與自動語言更新

本節是**已寫入開發分支的預覽實作介面**，並非 CI 或玩家實機驗證報告。

### 雙向私訊（不進公開頻道）

Discord `data/settings/dmcc.json`：在 `v3_features` 中設定 `"private_messages": true` 且 `"enabled": true`。既有帳號綁定仍為權限來源。

- 玩家在 Minecraft 使用 `/dmcc pm <玩家名稱> <訊息>`，訊息只在當前伺服器送給指定線上玩家以及發送者。Bridge 另外送 `player_private_message` 到 Gateway，**只有**收件者的 Minecraft UUID 已綁定 Discord，而且收件者同意接受私訊時，才會發送 Discord DM。
- 收件者先在 Discord 執行 `/dmcc dm-consent enabled:true`；取消則使用 `false`。同意設定儲存於 Bot 的私有 `data/dmcc/private_consent.json`（依 Bot 的資料庫根目錄配置），不向公共 Discord 發表。
- Discord 端可使用 `/dmcc whisper <server_id> <player_name> <message>`，發送者須綁定 Minecraft，收件者須已同意、綁定且為目標伺服器線上玩家。Bridge 以對應 UUID 將文字顯示給單一玩家，並回傳 `minecraft_private_response` 表示是否已送達。
- 原版 `/msg` 的所有攔截及與其他模組的私訊相容性**仍不是這個預覽版的能力**；目前提供明確的 `/dmcc pm` 與 Discord Slash 私訊替代路徑。無法直接把伺服器公開廣播視為私訊。

### 公開 Discord 系統／指令訊息

- `/dmcc broadcast` 是具權限門檻的公開發話指令，使用 `v3_features.templates.command`，不執行 Minecraft 任意指令。
- Discord 系統訊息的可讀摘要透過 `templates.system_message`。一般留言、回覆、編輯、刪除、表情反應與指令可對應 `user_message`、`response`、`edit`／`edited_message`、`delete`、`reaction`、`command` 等富文字片段。
- Discord Components 僅轉為可讀文字標籤，不傳送 Custom ID 或提交回應，也不嘗試觸發 Discord 的按鈕或選單互動。

### Minecraft ↔ Minecraft 跨服聊天格式

若啟用 `cross_server_relay=true` 與 `v3_features.enabled=true`，跨服 Relay 使用 `v3_features.message_parsing.minecraft_to_minecraft` 控制 Markdown、連結、時間戳、表情和顯示型提及格式。已啟用 Markdown 時可透過既有 `minecraft_components` 封包送安全的 Component 片段；禁用則退回純文字。只轉送允許的事件，不回寫來源伺服器以免循環。

### Fabric 原生聊天格式與熱重載

`config/minecraft-bridge.properties` 另有下列設定（初版預設為 `true`，但只有 `overwrite_native_messages=true` 時才替換原生簽章聊天）：

```properties
overwrite_native_messages=false
native_markdown=true
native_hyperlinks=true
native_timestamps=true
native_unicode_emojis=true
native_custom_emojis=true
native_mentions=true
# emoji.heart=♥
# emoji.bee=🐝
```

在 Minecraft OP 等級足夠的情況下執行 `/dmcc refresh`，即可重讀**顯示格式開關和語言**，而不重新建立 Gateway/TCP、授權及 OP 同步。Discord Bot 管理員的 `dmcc preview-refresh` 只更新預覽解析、模板及直接私訊選項；更改 Bot Gateway 埠、服務帳密或權限時，仍須使用既有模組重載流程。

### Mojang 官方語言自動更新

預設仍為手動下載。若管理員啟用：

```properties
translation_locale=zh_tw
language_auto_download=true
```

Fabric 會使用背景 Worker 在啟動後及約每 12 小時向**限定的 Mojang 官方 HTTPS 網域**取得與目前 Minecraft 版本相符的語言資源，確認資源索引及 SHA-1，原子更新 `config/minecraft-bridge/lang/mojang/<版本>/<語言>.json`。失敗時保留前一版。正式伺服器應評估網路權限與跨主機網路條件；不會在 Tick Thread 同步下載。

### 完成狀態與邊界

所有上述主要入口與程式路徑已提交到開發分支供直接測試。此批依使用者要求**沒有等待新 CI 驗收**，所有新功能均為實驗性；部分 Minecraft 1.21.8／1.21.9 映射 API、Discord 實際權限、Client UI 以及長時間壓力仍需要在你的環境校正。**請不要把「已提交原型」解讀成已驗證 DMCC v3 的 100% 行為對等。**
