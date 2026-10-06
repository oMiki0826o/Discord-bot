# Minecraft Backup and Restore

`mc_backup` is an owner-operated module for tmux-managed Minecraft servers. Configure absolute `server_dir` and `backup_dir` paths in `settings/mc_backup.json`; the backup directory must be outside the server directory.

Backups stop the server, create a validated tar archive and manifest, then restart it. Restores validate hashes and reject unsafe archive members before using a staging directory. Test a complete create-and-restore cycle on a disposable world before scheduling production backups, and maintain an off-host copy separately.

## Linux 範例

先建立備份目錄：

```bash
mkdir -p /srv/minecraft-backups/survival
```

`settings/mc_backup.json`：

```json
{
  "servers": [{
    "server_id": "survival",
    "server_dir": "/srv/minecraft/survival",
    "backup_dir": "/srv/minecraft-backups/survival",
    "tmux_session": "mc-survival",
    "start_argv": ["java", "-Xms2G", "-Xmx4G", "-jar", "server.jar", "nogui"],
    "keep_automatic": 7
  }],
  "history_limit": 200,
  "control_timeout_seconds": 30,
  "confirmation_timeout_seconds": 60
}
```

`server_dir`、`backup_dir` 都必須是已存在的絕對路徑，且備份目錄不能位於伺服器目錄中。以 Owner 身分先執行 `$mcbackup status`、`$mcbackup create`，確認 archive 可建立；再對測試世界完成一次 restore，才啟用排程。備份並不是異地備援，請另外同步 `/srv/minecraft-backups/` 到其他磁碟或主機。
