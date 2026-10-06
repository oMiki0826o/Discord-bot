# Discord Bot

![Version](https://img.shields.io/badge/version-v0.1.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tech](https://img.shields.io/badge/stack-Python%20%2B%20discord.py-lightgrey)
![Python](https://img.shields.io/badge/Python-3.11%2B-orange)

[中文](#中文) | [English](#english)

---

## 中文

### 目錄

- [關於](#關於)
- [功能](#功能)
- [安裝](#安裝)
- [使用方式](#使用方式)
- [授權](#授權)

### 關於

這是一個以 `discord.py` 開發的模組化 Discord Bot. Core 負責 Discord Client, 設定, 日誌, SQLite 基礎設施與模組生命週期. 伺服器管理, 音樂, 訊息, 工單與 AI 等功能則各自放在 `bot/mod/`, 可以獨立載入, 卸載與維護.

目前版本為 `v0.1.0`, 專案狀態為開發中. 原始碼公開於 [oMiki0826o/Discord-bot](https://github.com/oMiki0826o/Discord-bot).

### 功能

- **基本與系統管理**：`/help`、`/ping`、`/botinfo`，以及 Owner 專用的 Module、Settings、Slash Command、Presence 與 Bot Runtime 管理。
- **伺服器管理**：歡迎／離開訊息、自動身分組、伺服器設定、統計頻道與公告排程。
- **Moderation**：警告、Timeout、管理紀錄與執行期權限檢查。
- **音樂**：YouTube 搜尋與播放、佇列、收藏、循環、音量、互動控制與自然語言快捷操作。
- **社群工具**：自助身分組、Ticket、Join-to-Create 臨時語音頻道。
- **訊息工具**：一般訊息、Embed、Webhook 與自動回覆規則。
- **文件工具**：`/markitdown` 轉換支援的文件格式。
- **AI**：`/ai`、@Bot 對話、附件處理、受 scope 限制的 History／Memory／Knowledge 檢索，以及 Gemini Web／URL Context。
- **Agent（可選）**：有限回合的 Function Calling、只讀 Tools 與 Skill 載入；依賴 `ai` 模組。

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
- [Usage](#usage)
- [License](#license)

### About

A modular Discord Bot built with `discord.py`. Core owns the Discord client, settings, logging, SQLite infrastructure, module lifecycle, and shared interfaces. User-facing features live independently under `bot/mod/` so they can be loaded, unloaded, and maintained without coupling feature logic into startup code.

The current version is `v0.1.0` and the project is under active development. Source code is available at [oMiki0826o/Discord-bot](https://github.com/oMiki0826o/Discord-bot).

### Features

- **Core and owner operations**: `/help`, `/ping`, `/botinfo`, module management, settings, slash sync, presence, and runtime controls.
- **Guild management**: welcome/leave messages, autoroles, server settings, statistics channels, and scheduled announcements.
- **Moderation**: warnings, timeouts, moderation records, and runtime permission checks.
- **Music**: YouTube search/playback, queue, favourites, loop, volume, interactive controls, and natural-language shortcuts.
- **Community tools**: self-role panels, tickets, and Join-to-Create temporary voice channels.
- **Messaging**: plain messages, embeds, webhooks, and configurable auto-reply rules.
- **Documents**: `/markitdown` conversion for supported document formats.
- **AI**: `/ai`, mention conversations, attachments, scoped History/Memory/Knowledge retrieval, and Gemini Web/URL Context.
- **Agent (optional)**: bounded Function Calling, read-only tools, and progressive skill loading; depends on the `ai` module.

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
