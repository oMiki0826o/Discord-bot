# 從零安裝與啟動指南

這份指南給第一次部署本 Bot 的使用者。先讓 Bot 能登入 Discord，再依需要啟用 Minecraft bridge 或備份功能；不需要一次設定所有模組。

## 1. 準備條件

- Linux（Ubuntu / Debian 指令如下）、Python 3.11 以上、Git。
- Discord Developer Portal 建立的 Bot Token。
- 若使用 Minecraft：Java 21、Minecraft 1.21.8 Fabric Server、Fabric Loader 0.19.5 以上。
- 若使用本機控制或備份：`tmux`、`tar`，Bot 與 Minecraft 必須由同一個 Linux 使用者執行。

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y git python3.11 python3.11-venv tmux tar openjdk-21-jre
```

## 2. 安裝 Bot

```bash
git clone https://github.com/oMiki0826o/Discord-bot.git
cd Discord-bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

編輯 `.env`，至少填入：

```env
DISCORD_TOKEN=你的DiscordBotToken
OWNER_ID=你的Discord使用者ID
```

在 Discord Developer Portal 邀請 Bot 時，至少選取 `bot` 與 `applications.commands`。依啟用模組開啟需要的 Privileged Gateway Intents。

啟動：

```bash
python main.py
```

在 Discord 測試 `/ping`、`/help`。Owner 指令預設前綴為 `$`，可用 `$mod list` 查看已載入模組。

## 3. 啟用 Minecraft DMCC

Bot 與 Minecraft Server 在同一台主機時最簡單。DMCC 只接受 `127.0.0.1` 連線；不同主機不能直接把 Gateway 暴露到網路，必須自行建立 SSH tunnel 或 VPN。

把 `bridge/java_bridge.jar` 放進 Minecraft Server 的 `mods/`。建立：

```text
<Minecraft資料夾>/config/minecraft-bridge.properties
```

內容：

```properties
server_id=survival
gateway_host=127.0.0.1
gateway_port=8765
authentication_secret=請使用長且隨機的密碼
```

將同一段密碼加入 Bot `.env`：

```env
DMCC_SURVIVAL_SECRET=與authentication_secret完全相同的值
```

接著建立或修改 `settings/dmcc.json`。完整可用範例請見 [DMCC 設定](DMCC.md)。重新啟動 Bot 與 Minecraft，然後在 Discord 使用 `$dmcc status` 或 `/dmcc info` 確認 bridge 已連線。

## 4. 啟用本機 Minecraft 控制

在 `settings/dmcc.json` 設定 `local_tmux` provider。Minecraft 啟動方式與 `tmux_session` 必須和備份設定相同。啟動、停止與重啟由 Owner 指令執行：

```text
$dmcc server-status survival
$dmcc power survival start
$dmcc power survival stop
$dmcc power survival restart
```

`kill` 只在 server 設定明確允許 `allow_kill: true` 時使用；不要先在正式世界測試它。

## 5. 啟用備份與回檔

建立一個不在 Minecraft 資料夾內的備份目錄：

```bash
mkdir -p /srv/minecraft-backups/survival
```

設定 `settings/mc_backup.json`，範例請見 [備份與回檔設定](MC_BACKUP.md)。啟動 Bot 後，使用 `$mcbackup status`、`$mcbackup create` 建立第一份備份。務必先在測試世界實際回檔一次，才開啟排程或用於正式世界。

## 6. 日常更新

```bash
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python main.py
```

不要提交 `.env`、`settings/*.json`、`data/` 或世界與備份檔。這些都是你的部署資料，不會隨 Git 更新。
