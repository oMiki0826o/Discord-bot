# Settings

這個目錄保存 Bot 執行期間的非機密 JSON 設定。

第一次啟動時，Core 與各功能模組會依自己的 `DEFAULT_SETTINGS` 自動建立需要的 `settings/*.json`；既有設定只會補上缺少的預設欄位，並依 schema 驗證型別與範圍。

`settings/*.json` 屬於部署端設定，因此預設不納入版本控制與正式發布包。Token、API Key 等機密資料不可放在這裡，請使用專案根目錄的 `.env`。

## Minecraft 設定

啟用 Minecraft 時會用到兩個檔案：

- `dmcc.json`：Bridge、Discord relay、控制 provider 與權限。
- `mc_backup.json`：本機世界資料夾、備份資料夾、tmux session 與排程。

兩者都有主機路徑，請依自己的機器填寫。請參考[從零安裝與啟動指南](../docs/INSTALL.md)、[DMCC 設定](../docs/DMCC.md)與[備份／回檔設定](../docs/MC_BACKUP.md)。密鑰只放在 `.env`，不放在 JSON。


## AI 與 Agent 設定

載入 AI 時，Core 會建立 `ai.json`；啟用可選 Agent 時則建立 `agent.json`，兩者皆只補齊缺少的預設欄位。Gemini API Key 一律使用根目錄的 `.env` 中的 `GEMINI_API`，**不能寫在 JSON**。

`agent.json` 的 `max_model_turns`、`max_tool_calls`、`total_timeout_seconds`、`tool_timeout_seconds` 控制工具回合與執行上限。`privileged_users` 是少量可查詢唯讀 `$agentstatus` 的 Discord **User ID** 清單，例如：

```json
{
  "privileged_users": ["<@12345678987654321>"]
}
```

這只是設定片段，不是完整預設 `agent.json`。也可填純數字 User ID；Role Mention、`@everyone`、`@here` 均不可使用。這個清單不會授與 Owner 權限，也不會跨使用者開放私人記憶。

Agent 第一次啟動會建立 `data/agent/skills/使用說明.md`，請在本機資料夾新增自訂 Skill；不要放到公開的 `settings/` 或 Git 追蹤路徑。若需要 Redis，在 `.env` 設定 `AI_REDIS_URL`，不需要在 `agent.json` 中加入 Redis 密碼。
