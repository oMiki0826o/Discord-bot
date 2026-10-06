# 開發指南

這份指南給需要在本機修改、除錯或擴充 Bot 的開發者。單純部署請先閱讀專案根目錄的 [README](../README.md) 與[從零安裝與啟動指南](INSTALL.md)。

## 建立開發環境

```bash
git clone https://github.com/oMiki0826o/Discord-Bot.git
cd Discord-Bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

`.env` 至少填入 `DISCORD_TOKEN`。`OWNER_ID` 可以留空；AI / Agent 沒有啟用時，`GEMINI_API` 也可以留空。

啟動：

```bash
python main.py
```

## 修改應該放在哪裡

- `bot/core/`：兩個以上功能真正共用、且不理解特定業務的能力。
- `bot/mod/<module>/`：單一功能的 Discord 入口、服務、資料庫與 View。
- `settings/*.json`：部署端產生的非機密設定；不要把個人設定提交進 Git。
- `tests/`：可離線驗證的行為與回歸測試。
- `tools/`：匯入、維護與發布工具。

判斷原則：移除某個 Feature Module 後，如果 Core 仍必須保留那段程式碼，它才適合放進 Core。

## Settings 與資料庫

新增設定時，先在模組自己的 `config.py` 定義：

1. `DEFAULT_SETTINGS`。
2. Settings schema。
3. 需要時加入 schema migration。

不要在多個模組各自硬編碼相同設定，也不要把 Token / API Key 放入 `settings/*.json`。

SQLite schema 與 repository 應由使用資料的模組擁有。Core 的 `bot/core/database/` 只提供共同的連線與 migration 機制。

## 驗證改動

完整依賴已安裝時，發布前至少執行：

```bash
python -m pytest -q
python -m compileall -q bot tools tests main.py
git diff --check
```

離線測試應涵蓋：

- 設定 parsing / schema / migration。
- Module metadata 與 dependency graph。
- Repository 與資料 migration。
- 權限判斷。
- Queue / formatter / routing / context 等純邏輯。
- 發布包不可包含的檔案。

Discord API、Voice、FFmpeg、yt-dlp、Gemini 與實際權限仍需在測試伺服器做整合驗證。尤其是 Module reload、Slash sync、Voice reconnect 與外部 API error handling。

## 音樂開發

音樂功能需要 FFmpeg：

```bash
ffmpeg -version
python -m yt_dlp --version
```

YouTube `403`、signature extraction 或串流網址失效經常來自上游變動。先確認 `yt-dlp` 與 FFmpeg，再判斷是否需要修改 Bot 邏輯。

## AI / Agent 開發

AI 的跨模組公開邊界是 `bot.mod.ai.api`。`agent` 不應直接操作 AI 的 SQLite、Provider secret 或 Discord Client。

Web／URL Context 與模型可用性屬於外部服務能力，不能只靠單元測試證明。測試應至少區分：正常回覆、429 quota、503/unavailable、timeout、empty response 與 grounding verification failure。

## GitHub 推送前檢查

請使用 Git 或 GitHub Desktop 推送, 不要在 GitHub 網頁直接上傳整個工作目錄。`.gitignore` 會排除 `.env`, `data/`, `settings/*.json`, 虛擬環境, cache, `dist/` 與 `tools/`。

```bash
git add .
git status
```

確認暫存清單只包含可公開的程式, 文件, 依賴宣告與範本後再提交。此 repository 是 Public, 已提交的 Python 原始碼會公開可見。
