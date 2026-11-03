# AI / Agent 模組架構

> 本文件描述 Discord Bot 的 AI 與 Agent v2.3 開發分支。功能是否正式可用以 GitHub Actions 測試結果與部署驗收為準。

## 核心分工

- `bot/mod/ai/`：Gemini Provider、上下文、Memory/History、知識索引、檢索、資料存取、Discord 入口、使用量統計。
- `bot/mod/agent/`：自製多回合 Tool Loop、Capability 及執行上限、只讀 Tool Registry、Skills、MCP。
- `bot/core/documents/`：共用 MarkItDown 文件轉換服務；使用背景執行緒處理同步轉換。
- `bot/mod/agent/mcp/`：使用官方 MCP Python SDK 2.x 建立**無網路連接埠**的本機唯讀 Knowledge Server。不得接受模型提供的任意 SQL、存取 Token 或檔案路徑。

## Discord 介面

只允許起始 `<@BotID>`、`<@!BotID>` 或 `/ai` 呼叫。身分組、`@everyone`、`@here`、一般文字中的 Bot Mention 不會觸發聊天。

一般回覆維持 Discord 純文字，不使用 Embed 與 emoji。耗時較長才出現狀態訊息；狀態由實際 Context、Model、Tool 事件驅動，最終編輯為完整答案。短請求不顯示額外的進度訊息。

回覆末尾的 `-#` 小字明確分別顯示 **輸入與輸出 Token**，可選擇顯示 Gemini reported thinking tokens、模型名稱與耗時。若 API 沒有傳回 Usage Metadata，顯示 `—`；不得冒用推算值為實際值。標示的 Token/s 是整次回覆平均（非模型解碼速度）。

## 使用者自訂 Skills

首次啟動在 `data/agent/skills/` 建立 `使用說明.md`，使用者自行建立 `<skill-name>/SKILL.md`。重新啟動不覆寫已有檔案。Skill 只有文字工作指引，沒有指令執行能力；限制大小、路徑穿越及符號連結逃逸。

## 權限

一般使用者可透過 AI 讀取其自身範圍內的私人記憶與授權的頻道內容。MCP 限制為 Owner Knowledge 的唯讀查詢。

`settings/agent.json` 的 `privileged_users` 可使用 **Discord 使用者 Mention** 或純 ID：

```json
{"privileged_users": ["<@12345678987654321>"]}
```

這些使用者可執行唯讀 `$agentstatus`（前綴仍依 Bot 設定），**不會**取得其他人的私人記憶，也不會取得 Owner 管理命令權限。

## Redis（可選）

在執行環境設定 `AI_REDIS_URL=redis://host:6379/0` 才啟用 Redis。Redis 保存 SHA-256 雜湊的使用者 ID 與短期速率限制計數器；公開 Knowledge 搜尋只快取雜湊查詢鍵、Chunk ID 與必要排序中繼資料，命中時必須重新讀取並驗證 Knowledge 原稿。不快取個人化模型回答、對話、私人記憶或 API Key。Redis 斷線時回退到本機 Guard，不阻止所有請求；單一進程正常運作不需要安裝 Redis Server。

## 偵錯與部署

仍由 `python main.py` 啟動，延續目前的 SQLite、設定檔、Memory 和 Knowledge。現階段不需要 Docker。

開發驗證：

```bash
ruff check bot tools tests main.py
pytest -q
python -m compileall -q bot tests
```

必須另外在私人 Discord 測試伺服器檢查 Mention、Slash、進度訊息編輯、真實 Gemini 模型的 Token Metadata 和 MCP 整合；CI 的 Fake SDK 與模擬測試不能取代上線驗收。

## 安全邊界

- MCP 不提供 SQL 通道、文件寫入或 Shell 執行。
- Skill、RAG 與工具回傳內容都是不可信資料，不得變成 System Prompt 或權限證明。
- 不依賴模型自行判斷資料權限；Scope 限制由 Python 業務服務檢查。
- `data/`、`.env`、機密與個人資料不得提交至公開 GitHub。
- Docker / 其他容器化工作在獨立部署階段進行。
