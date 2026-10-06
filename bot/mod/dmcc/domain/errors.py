"""bot/mod/dmcc/domain/errors.py
Stable DMCC errors safe for translation at adapter boundaries.

Modification():

- Integrated into the production Discord bot.
"""


class DmccError(Exception):
    """Base class for expected DMCC failures."""


class ServerNotFound(DmccError):
    """A configured server ID was not found."""


class CapabilityUnavailable(DmccError):
    """A server does not expose the requested capability."""


class AuthorizationError(DmccError):
    """The actor does not have the required DMCC permission level."""


class ProviderConfigurationError(DmccError):
    """A provider definition cannot be safely loaded."""


class ProviderConnectionError(DmccError):
    """A provider could not be reached or returned an invalid response."""


class OperationBusy(DmccError):
    """A destructive operation is already active for the server."""


class OperationTimeout(DmccError):
    """An operation did not finish inside its bounded timeout."""


class BackupValidationError(DmccError):
    """A backup request or artifact failed validation."""


class BackupOperationError(DmccError):
    """Creating a backup failed."""


class RestoreOperationError(DmccError):
    """Restoring a backup failed."""


class RestoreRollbackError(DmccError):
    """A failed restore could not be fully rolled back."""


class ImportConflict(DmccError):
    """Imported identity data conflicts with the source of truth."""
