# Discord Bot

![Version](https://img.shields.io/badge/version-v0.3.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tech](https://img.shields.io/badge/stack-Python%20%2B%20discord.py-lightgrey)
![Python](https://img.shields.io/badge/Python-3.11%2B-orange)
[![CI](https://github.com/oMiki0826o/Discord-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/oMiki0826o/Discord-bot/actions/workflows/ci.yml)

[中文](#中文) | [English](#english)

---

## 中文

### 目錄

- [關於](#關於)
- [功能](#功能)
- [安裝](#安裝)
- [AI / Agent 設定](#ai--agent-設定)
- [Minecraft 與備份](#minecraft-與備份)
- [使用方式](#使用方式)
- [授權](#授權)

### 關於

這是一個以 `discord.py` 開發的模組化 Discord Bot. Core 負責 Discord Client, 設定, 日誌, SQLite 基礎設施與模組生命週期. 伺服器管理, 音樂, 訊息, 工單與 AI 等功能則各自放在 `bot/mod/`, 可以獨立載入, 卸載與維護.

目前版本為 `v0.3.0`, 專案狀態為開發中. 原始碼公開於 [oMiki0826o/Discord-bot](https://github.com/oMiki0826o/Discord-bot).

### 功能

- **基本與系統管理**：`/help`、`/ping`、`/botinfo`，以及 Owner 專用的 Module、Settings、Slash Command、Presence 與 Bot Runtime 管理。
- **伺服器管理**：歡迎／離開訊息、自動身分組、伺服器設定、統計頻道與公告排程。
- **Moderation**：警告、Timeout、管理紀錄與執行期權限檢查。
- **音樂**：YouTube 搜尋與播放、佇列、收藏、循環、音量、互動控制與自然語言快捷操作。
- **社群工具**：自助身分組、Ticket、Join-to-Create 臨時語音頻道。
- **訊息工具**：一般訊息、Embed、Webhook 與自動回覆規則。
- **文件工具**：`/markitdown` 轉換支援的文件格式。
- **AI**：`/ai`、直接 @Bot 對話、附件與 MarkItDown、History／Memory／Knowledge 權限隔離、Gemini Web／URL Context、原生訊息進度與輸入／輸出 Token 統計。
- **Agent（可選）**：有限回合 Function Calling、Skills 自動初始化與漸進載入、官方 MCP SDK 的本機唯讀 Knowledge Tools、Discord ID 管理員診斷；依賴 `ai` 模組。
- **Minecraft 維運**：Fabric DMCC bridge、Discord ↔ Minecraft 訊息轉送、可自訂的 Bot/Webhook 玩家聊天與伺服器事件顯示、Discord 表情／貼圖／附件／投票摘要與反應轉送、選用 Discord 暱稱同步／玩家提及提醒／GitHub 發布通知、選用 MSPT 警告／頻道狀態／Presence／模組更新通知、Owner 本機控制，以及 tmux + tar 的安全備份／回檔。

### 安裝

需求: Python 3.11 以上, Discord Bot Token. 音樂播放需要 FFmpeg, AI 或 Agent 需要 Gemini API Key. macOS 使用 `/markitdown` 轉換 PDF 時需要 macOS 13 以上.

```bash
git clone https://github.com/oMiki0826o/Discord-bot.git
cd Discord-bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

編輯 `.env`：

```env
DISCORD_TOKEN=你的_Discord_Bot_Token
OWNER_ID=
GEMINI_API=
```

只有 `DISCORD_TOKEN` 是整個 Bot 的必要環境變數。`OWNER_ID` 留空時會使用 Discord Application Owner／Team Owner；不使用 AI 時可讓 `GEMINI_API` 保持空白。

一般功能設定不需要手動複製範本。第一次載入 Core 或模組時，Bot 會依程式內的預設值建立對應的 `settings/*.json`。這些檔案屬於部署端設定，預設不提交到 Git。


### AI / Agent 設定

啟用 AI 時，在本機 `.env` 設定 `GEMINI_API`。第一次啟動會自動建立 `settings/ai.json`、`settings/agent.json`（啟用 Agent 時）與 `data/agent/skills/使用說明.md`；不會覆寫既有 Skills。手動在 `data/agent/skills/<skill-name>/SKILL.md` 新增文字工作指引，Skill 不能自行取得工具權限或執行程式碼。

Discord AI 只接受**訊息開頭直接** `<@BotID>`、`<@!BotID>` 與 `/ai`，不接受 `@everyone`、`@here`、身分組或句中提及。一般問題直接回覆；較長的工作會更新同一則純文字訊息，完成後編輯成正式答案。頁尾 `-#` 分別顯示**輸入與輸出 Token**、可用的思考 Token、耗時，以及標示為「端到端」的平均 Token/s。若 API 沒提供實際用量，會顯示 `—`。

少量高權限使用者可在本機 `settings/agent.json` 的 `privileged_users` 設定為 `["<@12345678987654321>"]` 或純數字 ID，使用 `$agentstatus` 查看**唯讀執行狀態**；這不會開放他人的私人記憶。若需要可選 Redis，於 `.env` 設定 `AI_REDIS_URL=redis://127.0.0.1:6379/0`。沒有 Redis 仍可在本機運行，Redis 不存放完整私人對話與模型回覆。

Knowledge 透過官方 MCP Python SDK 的**本機唯讀**服務搜尋，不提供任意 SQL、修改資料或對外 HTTP Port。詳細安全限制、資料生命週期及測試方式請參考 [AI / Agent 架構](docs/AI_AGENT_ARCHITECTURE.md)、[AI 模組](bot/mod/ai/README.md)、[Agent 模組](bot/mod/agent/README.md)。協作紀錄、測試草稿、`data/`、`.env`、`settings/*.json` 為本機資料，禁止提交至公開倉庫。

### Minecraft 與備份

> **Fabric DMCC v3 功能初版（開發分支）**：已提供 [預覽架構、功能矩陣、設定與試用說明](docs/DMCC-FABRIC-V3-PREVIEW.md) 和 [範例設定](docs/examples/dmcc-v3-preview.json)。新功能採明確啟用、尚未完整實機驗證；正式版請仍參照 [DMCC 使用文件](docs/DMCC.md)。


第一次部署請直接閱讀[從零安裝與啟動指南](docs/INSTALL.md)。其中包含 Linux 套件、Fabric bridge、DMCC、tmux 控制、備份與回檔的完整步驟。Fabric Bridge 在 CI 中針對 Minecraft **1.21.8** 及 **1.21.9** 個別編譯與測試，請安裝**相符版本**的 JAR；其他版本不可視為已驗證。

- [DMCC / Minecraft Bridge 設定](docs/DMCC.md)
- [Minecraft 備份與回檔設定](docs/MC_BACKUP.md)
- [Fabric bridge 說明與 checksum](bridge/README.md)

### 使用方式

在 Discord Developer Portal 依你啟用的模組開啟需要的 Privileged Gateway Intents，邀請 Bot 時至少包含 `bot` 與 `applications.commands` scope，然後執行：

```bash
python main.py
```

可以先確認：

```text
/help
/ping
/botinfo
/ai 幫我用三句話介紹這個伺服器
```

`/help` 會依實際載入的模組整理 Slash Command。Owner 維運指令使用 `settings/bot.json` 的 Prefix，預設是 `$`：

```text
$help
$bot status
$bot health
$mod list
$settings status
$ai status
$ai models
$ai quota
$ai data sync
$ai index status
$bot stop
```

### 授權

本專案採用 MIT 授權, 詳見 [LICENSE](./LICENSE).

---

## English

### Table of Contents

- [About](#about)
- [Features](#features)
- [Installation](#installation)
- [AI / Agent configuration](#ai--agent-configuration)
- [Minecraft and backups](#minecraft-and-backups)
- [Usage](#usage)
- [License](#license)

### About

A modular Discord Bot built with `discord.py`. Core owns the Discord client, settings, logging, SQLite infrastructure, module lifecycle, and shared interfaces. User-facing features live independently under `bot/mod/` so they can be loaded, unloaded, and maintained without coupling feature logic into startup code.

The current version is `v0.3.0` and the project is under active development. Source code is available at [oMiki0826o/Discord-bot](https://github.com/oMiki0826o/Discord-bot).

### Features

- **Core and owner operations**: `/help`, `/ping`, `/botinfo`, module management, settings, slash sync, presence, and runtime controls.
- **Guild management**: welcome/leave messages, autoroles, server settings, statistics channels, and scheduled announcements.
- **Moderation**: warnings, timeouts, moderation records, and runtime permission checks.
- **Music**: YouTube search/playback, queue, favourites, loop, volume, interactive controls, and natural-language shortcuts.
- **Community tools**: self-role panels, tickets, and Join-to-Create temporary voice channels.
- **Messaging**: plain messages, embeds, webhooks, and configurable auto-reply rules.
- **Documents**: `/markitdown` conversion for supported document formats.
- **AI**: `/ai`, direct bot mentions, attachments and MarkItDown, scoped History/Memory/Knowledge retrieval, Gemini Web/URL Context, native message progress and separate input/output token reporting.
- **Agent (optional)**: bounded Function Calling, auto-initialized Skills, read-only Knowledge tools through the official MCP Python SDK, and Discord-ID status access; requires the `ai` module.
- **Minecraft operations**: Fabric DMCC bridge, two-way Discord relay, configurable Bot/Webhook chat and event presentation, readable Discord emoji/sticker/attachment/poll summaries and reactions, optional linked-account nickname sync, targeted mentions and GitHub release notices, optional MSPT alerts, channel/Presence status, Modrinth update checks, owner-operated local control, and tmux + tar backup/restore.

### Installation

Requirements: Python 3.11 or newer and a Discord Bot Token. FFmpeg is required for music playback. A Gemini API key is required only for AI or Agent modules. PDF conversion through `/markitdown` requires macOS 13 or newer on macOS.

```bash
git clone https://github.com/oMiki0826o/Discord-bot.git
cd Discord-bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
OWNER_ID=
GEMINI_API=
```

Only `DISCORD_TOKEN` is required for the whole application. When `OWNER_ID` is empty, the bot resolves the Discord Application Owner/Team Owner. Leave `GEMINI_API` empty when AI is not enabled.

Feature settings are generated as `settings/*.json` from module defaults when they are first loaded. These files are deployment-local and are not tracked by default.


### AI / Agent configuration

Set `GEMINI_API` in your local `.env` when enabling AI. On first launch, the modules create `settings/ai.json`, `settings/agent.json` (if Agent is enabled), and `data/agent/skills/使用說明.md`. Existing Skills are preserved. Add optional text-only instructions in `data/agent/skills/<skill-name>/SKILL.md`; Skills cannot grant themselves tool privileges or execute programs.

AI responds only to a **direct leading** `<@BotID>` or `<@!BotID>` mention, or the `/ai` command. Broadcasts, role mentions and inline mentions cannot trigger AI. Short answers use a normal message; longer tasks update one plain-text status message and replace it with the answer. The `-#` footer shows **separate input and output tokens**, reported thinking tokens where available, elapsed time and explicitly labeled end-to-end tokens/s. Missing provider usage is shown as `—` rather than fabricated.

For limited read-only status access, populate `privileged_users` in your local `settings/agent.json` with Discord IDs or mentions such as `["<@12345678987654321>"]`, then use `$agentstatus`. This does **not** provide access to another user's private memories. Redis is optional; set `AI_REDIS_URL=redis://127.0.0.1:6379/0` in `.env` only if using it. The bot operates without Redis and does not cache private model answers in Redis.

Knowledge search uses a **local read-only** MCP adapter based on the official MCP Python SDK; there is no raw SQL, data-write tool or public MCP HTTP port. See [AI / Agent architecture](docs/AI_AGENT_ARCHITECTURE.md), [AI module](bot/mod/ai/README.md) and [Agent module](bot/mod/agent/README.md). Private collaboration notes, `data/`, `.env` and `settings/*.json` are local-only and must never be committed.

### Minecraft and backups

> **Fabric DMCC v3 preview (development branch)**: See the [architecture, feature matrix and manual testing notes](docs/DMCC-FABRIC-V3-PREVIEW.md) and [configuration example](docs/examples/dmcc-v3-preview.json). Optional features are experimental, not yet fully verified with live Discord and Minecraft clients.


For a first deployment, follow the [step-by-step installation guide](docs/INSTALL.md). Fabric Bridge is built per Minecraft **1.21.8** and **1.21.9** in CI; install only the JAR targeting the server's exact version. Other game versions are unverified. It covers Linux packages, the Fabric bridge, DMCC, tmux control, backup, and restore.

### Usage

Enable the Privileged Gateway Intents required by your selected modules in the Discord Developer Portal, invite the bot with at least the `bot` and `applications.commands` scopes, then run:

```bash
python main.py
```

Useful first commands:

```text
/help
/ping
/botinfo
/ai Summarise this server in three sentences.
```

Owner operations use the configured prefix (`$` by default):

```text
$help
$bot status
$bot health
$mod list
$settings status
$ai status
$ai models
$ai quota
$ai data sync
$ai index status
$bot stop
```

### License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).
