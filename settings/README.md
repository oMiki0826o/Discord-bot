# Settings

這個目錄保存 Bot 執行期間的非機密 JSON 設定。

第一次啟動時，Core 與各功能模組會依自己的 `DEFAULT_SETTINGS` 自動建立需要的 `settings/*.json`；既有設定只會補上缺少的預設欄位，並依 schema 驗證型別與範圍。

`settings/*.json` 屬於部署端設定，因此預設不納入版本控制與正式發布包。Token、API Key 等機密資料不可放在這裡，請使用專案根目錄的 `.env`。

## Minecraft 設定

啟用 Minecraft 時會用到兩個檔案：

- `dmcc.json`：Bridge、Discord relay、控制 provider 與權限。
- `mc_backup.json`：本機世界資料夾、備份資料夾、tmux session 與排程。

兩者都有主機路徑，請依自己的機器填寫。請參考[從零安裝與啟動指南](../docs/INSTALL.md)、[DMCC 設定](../docs/DMCC.md)與[備份／回檔設定](../docs/MC_BACKUP.md)。密鑰只放在 `.env`，不放在 JSON。
