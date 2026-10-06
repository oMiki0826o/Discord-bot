"""bot/mod/mc_backup/domain/errors.py

Typed failures for standalone backup operations.

Modification():

- Integrated into the production Discord bot.
"""


class McBackupError(RuntimeError):
    """Base class for expected mc_backup failures."""


class BackupConfigurationError(McBackupError):
    """Settings are unsafe or inconsistent."""


class BackupDataError(McBackupError):
    """Persisted JSON data is malformed."""


class BackupOperationError(McBackupError):
    """A backup, restore, or archive operation failed."""
