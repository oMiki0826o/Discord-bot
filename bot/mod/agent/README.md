# Agent Feature Module

`agent/` 是可選的進階 AI 執行模組，正式位置為 `bot/mod/agent/`。它宣告
`MODULE_DEPENDENCIES = ("ai",)`，並只透過 `bot.mod.ai.api` 取得基礎 AI 能力。

## 安裝與行為

1. 先安裝完整的 `ai/` Module。
2. 將本目錄複製為 `bot/mod/agent/`。
3. ModuleLoader 會先載入 `ai`，再載入 `agent`。
4. Extension 會建立 `settings/agent.json`、只讀管理指令 Cog，但不建立資料庫或 Provider client。

載入後，Agent 取代 AI 的 active runtime；卸載後立即回復 `BasicRuntime`，
`@Bot` 與 `/ai` 仍可正常使用。AI reload 時，Agent factory 會以新的 AI services
重建 runtime，不保留舊 Provider 或 DB reference。

## 提供的能力

- Function Calling 與有限多回合 Tool Loop。
- Tool capability、argument schema、timeout 與數量限制。
- Duplicate Tool Call 防護與強制收尾。
- Skill metadata 先列出，需要時才讀取完整 `SKILL.md`。
- Read-only Agent 失敗時最多降級重試一次 BasicRuntime。

## 工具與權限

內建工具全部只讀：

- `search_user_memory`：只查發起者的 private memory。
- `search_history`：發起者與當前頻道的 History。
- `read_topics`：發起者與當前頻道的 Topic State。
- `read_public_profile` / `search_public_profiles`：可查他人，但只讀明確公開欄位。
- `search_knowledge` / `read_knowledge_chunk`：Owner 索引的 Knowledge。
- `read_channel_context`：只讀當前頻道，並由 AI adapter 檢查 Discord 權限。
- `list_skills` / `read_skill`：只讀 `data/agent/skills/`。

模型不能指定 private `user_id` 或 `channel_id`，也無法存取 SQLite connection、
Discord Client、任意檔案路徑、Shell、API key、token 或其他 Feature Module。

## Settings

`settings/agent.json` 包含 Agent-owned budget 與 Discord ID 唯讀管理員名單：

- `max_model_turns`
- `max_tool_calls`
- `total_timeout_seconds`
- `tool_timeout_seconds`
- `privileged_users`（只影響 `$agentstatus` 唯讀管理資訊）

AI Provider、Memory、Prompt、Context 與 Attachment 設定仍屬於 `settings/ai.json`。

## v0.3.0 重構更新

- `tools/` 與 `skills/` 正式套件重構（保留舊 `builtin_tools.py` 匯出）。
- 首次啟動自動建立 `data/agent/skills/使用說明.md`；不覆寫使用者 Skill。
- 本地唯讀 MCP 轉接 Knowledge 索引，無外部連接埠，不提供 SQL 或寫入。
- `settings/agent.json` 可使用 `privileged_users: ["<@12345678987654321>"]` 指定少量使用者檢視唯讀 `$agentstatus`。
- Agent 多回合用量彙總、真實執行事件由 AI Discord 層顯示。

更多詳見 [AI / Agent 架構](../../../docs/AI_AGENT_ARCHITECTURE.md)。

## 第一次啟動與自訂 Skill

Agent 載入時建立 `data/agent/skills/` 與 `使用說明.md`（已存在時不覆寫）。每個 Skill 是一個含有 `SKILL.md` 的子目錄（例如 `data/agent/skills/minecraft/SKILL.md`），必須使用安全的小寫名稱。Skill 只提供文字指引，不能授權寫入、執行指令或讀取其他人的記憶。單份檔案上限為 128 KiB，拒絕符號連結逃逸。直接修改 `SKILL.md` 後下次讀取便使用新版內容。

## 唯讀 MCP Knowledge

MCP 使用官方 Python SDK 的本地進程內連線，無外部 HTTP Port、無任意 SQL 與修改資料功能。提供 `knowledge_search`、`knowledge_read_chunk` 及 `knowledge_list_sources`，透過 AI 公開 Facade 讀取 Owner Knowledge 並檢核來源。記憶、頻道歷史及私人資料仍留在具使用者 Scope 的 AI 服務，不經此通用 MCP 伺服器。

## Discord ID 管理

`settings/agent.json` 為自動建立的本機設定。以下只是設定片段，應在現有 JSON 物件加入欄位：

```json
{
  "privileged_users": ["<@12345678987654321>"]
}
```

允許純數字 Discord User ID 與 `<@id>`、`<@!id>`；禁止 `<@&role>` 與廣播。Owner 與列出的人員可以使用 `$agentstatus` 查看唯讀執行狀態（Prefix 依本機 Bot 設定調整），**不會取得 Owner 操作權限，也無法讀取他人的私人記憶**。

## 可靠性與限制

Agent 使用真實 Context、Model、Tool 事件更新原本的 Discord 訊息，並彙總 Gemini 每回合回傳的輸入／輸出／思考 Token。工具有 Capability、Timeout、Output Budget 與去重限制，必要時由 `RuntimeHost` 安全降級到基礎 AI。對於 Gemini 同一回合同時傳回文字與工具呼叫的情況，優先處理工具呼叫，避免把暫時文字誤判成最終答案。

請在正式部署前先於私人測試 Discord 伺服器檢查 Slash、Mention、Cog Reload、Gemini Metadata、Skill 讀取及 MCP。CI 不會使用真實 Discord Token 或外部服務帳號。

