# AI Feature Module

`ai/` 是可獨立搬至 `bot/mod/ai/` 的 Discord-Bot Feature Module。它只透過
`extension.py` 使用 Core 的通用設定、Module Loader 與資料目錄，不要求
Core 理解 Gemini、Memory、Prompt 或 Retrieval。

只安裝 `ai/` 就是完整的基礎 AI：`@Bot` 與 `/ai` 可聊天，並由程式依意圖
取得受 scope 限制的 History、Memory、Topic、Public Profile、Knowledge 與當前
Channel Context。它也會儲存 Event，並在回覆後以 durable job 更新長期記憶。
不安裝 `agent/` 不會破壞這些功能。

## 安裝

1. 將整個目錄複製為 `bot/mod/ai/`。
2. 本專案已在 `requirements.txt` 宣告 AI 所需依賴；若把此模組獨立搬到其他專案，
   請同步加入 `discord.py>=2.7` 與 `google-genai>=2.5`（並更新該專案的 lock 檔，如有）。
3. 如需 PDF/DOCX/PPTX/XLSX 解析，安裝 `markitdown[pdf,docx,pptx,xlsx,xls]>=0.1.6`。
4. 在 `.env` 設定 `GEMINI_API`。Secret 不寫入 JSON 或原始碼。
5. 讓現有 ModuleLoader 載入 `bot.mod.ai.extension`。

Extension 會透過 `settings.register("ai", DEFAULT_SETTINGS, SETTINGS_SCHEMA)` 建立/合併
`settings/ai.json`，並在 `data/database/ai.db` 建立自有 schema。不需修改
`startup.py`、Core settings defaults 或 Core database。

## 資料位置

- `data/database/ai.db`：Event、Memory、Topic、Profile、Knowledge index 與 Job。
- `data/ai/prompt/`：首次啟動後的可編輯 Prompt 與 `personas/` 人格資料。
- `data/ai/users_memory/`：Owner 維護的手動記憶 JSON；`$ai data` 會正規化並同步為 SQLite 查詢投影。
- `data/ai/auto_memory/`：AI 自主記憶的 Owner 可編輯鏡像；SQLite 仍是 Runtime 查詢權威。
- `data/ai/knowledge/`：Owner 可修改的 `.md` / `.txt` 知識來源。
- `resources/prompt/` 與 `resources/templates/`：首次初始化的中立模板。

私人使用者資料與本機 Prompt override 不應提交到公開 Repository。

## Discord 入口

- `<@BotID> <message>`：**起始** Bot Mention 對話；廣播、Role Mention 與句中提及不觸發。
- `/ai prompt:<message> [attachment]`：Slash 對話。
- `$ai status`、`$ai models`、`$ai quota`、`$ai cache`、`$ai prompt`、`$ai reload`：Owner 管理。
- `$ai index [rebuild|status]`：重建或查看 Knowledge index；直接執行 `$ai index` 等同 rebuild。
- `$ai diagnose memory`：查看自主記憶鏡像掃描、錯誤與 Owner 封鎖狀態。
- `$ai persona list|current|set|reload`：Owner-only 人格切換。
- `$ai profile show|set|remove`：Owner 明確維護可對外查詢的 Public Profile。

Mention 與 Slash 共用同一 `AIService`、Guard、Active Runtime、Provider 與
Memory Pipeline。

## AI 回覆與執行進度（v0.3.0）

Discord 介面維持一般訊息，不使用 Embed 或 emoji。僅接受位於訊息開頭的真實 Bot Mention（`<@BotID>` 或 `<@!BotID>`）及 `/ai`；`@everyone`、`@here`、Role Mention、句中提及與引用內容都不算呼叫。

短問題直接回覆；需要較久時間的請求會先顯示由程式發出的真實 Context／Model／Tool 事件，再將**同一則**訊息編輯成答案。事件不包含模型內部推理、Prompt 原文、私人記憶或 Tool 參數；Discord 更新採限速，避免大量 API 請求。

回覆最後使用 Discord `-#` 小字，分別標示**輸入與輸出 Token**、可用時的 Gemini 思考 Token、耗時，以及「端到端」平均 Token/s。使用量優先採 Gemini API Metadata，多回合 Agent 會累加。缺少 Metadata 時顯示 `—`，不將估算值當成測量結果。

## Redis 與快取

Redis **非必需**。若環境設定 `AI_REDIS_URL=redis://127.0.0.1:6379/0`，使用 Redis 存放短期的匿名化速率限制計數器與公開 Knowledge Chunk ID／排名資訊；命中後仍要重新驗證來源原稿。Redis 斷線則回退原有單進程 Guard 與 SQLite 檢索。私人 History／Memory 與個人化回答不寫入 Redis 共用快取。

Search Cache 取消跨不同查詢的 fuzzy 命中；可快取回覆必須包含使用者、頻道、模型、上下文與系統指令的隔離鍵。時效性搜尋或含網址的請求不重用舊的完整回答。既有 SQLite 資料保留不變。

詳細介面、Agent 依賴及安全限制見 [AI / Agent 架構](../../../docs/AI_AGENT_ARCHITECTURE.md)。

## 基礎檢索與權限

Basic Context Planner 依 Router 的保守意圖判斷取得參考資料，不讓模型直接
操作資料庫。

- 自動 Private Memory 固定使用 requester scope，且保留 Event Evidence；`users_memory/*.json` 是同樣受 requester scope 限制的手動原稿。
- History 與 Topic 固定使用 requester 與 current channel scope。
- 詢問其他人時只可讀取 Owner 明確維護的 Public Profile。
- Channel Context 必須通過 `view_channel` 與 `read_message_history` 權限檢查。
- Knowledge 只來自 Owner 管理的原始檔；索引只負責找候選，送進模型前會重新讀取並驗證原稿。

若需要 Function Calling、漸進 Skill 與多回合 Tool Loop，可另外安裝同層的
`agent/` Module。Agent 只透過 `ai/api.py` 使用這些已限制 scope 的能力。

## Retrieval 與降級

History 與 Knowledge 以 SQLite FTS5 作為基礎，中文文字有 CJK bigram 正規化。
Knowledge 可用 Gemini Embedding、float32 BLOB、cosine 與 RRF 合併。Embedding
的 429、503、timeout 或索引失敗只會降級到 FTS5。

`ai.db` 的 FTS、chunk 與向量都是可重建索引，而非 Knowledge 的內容真相。Owner
變更或刪除 `data/ai/knowledge/` 原稿後可執行 `$ai index rebuild`（或直接 `$ai index`）；重建同時清除已刪除來源的索引。

## 網頁搜尋與網址讀取

使用者明確要求搜尋（例如「幫我查一下網路」、「搜尋最新新聞」），或訊息包含
`http://`／`https://` 網址時，Router 會開放 Gemini 管理的 Web capability；含網址的
請求也會開放 URL Context，讓 Provider 嘗試讀取該頁面。

這不是 Bot 自行繞過網站限制的爬蟲。可用性仍取決於 Gemini、網站的公開性與頁面格式；
Provider 無法讀取時，回答必須說明限制，不能假稱已經瀏覽或驗證內容。

## Lifecycle

`AiModule.start()` 恢復 durable Memory Jobs。Extension 卸載時由 `teardown()` 移除 Cog，
並在 `finally` 中呼叫 `module.close()`，等待 worker 停止、關閉 Provider client 與清理
in-memory state；Cog 本身只處理自己的 Discord-side cleanup。移除整個 `bot/mod/ai/`
不影響 Core 啟動，且不會自動刪除模組資料。

## 舊資料搬遷

`migration.LegacyMigrator` 只讀開啟舊 SQLite，驗證欄位後搬移 Event，並只匯入
能追溯到 user message evidence 的 active memory。搬遷完成後不需、也不應
在 Runtime 保留舊 schema/path fallback。
