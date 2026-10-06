# Minecraft Backup and Restore

`mc_backup` is an owner-operated module for tmux-managed Minecraft servers. Configure absolute `server_dir` and `backup_dir` paths in `settings/mc_backup.json`; the backup directory must be outside the server directory.

Backups stop the server, create a validated tar archive and manifest, then restart it. Restores validate hashes and reject unsafe archive members before using a staging directory. Test a complete create-and-restore cycle on a disposable world before scheduling production backups, and maintain an off-host copy separately.
