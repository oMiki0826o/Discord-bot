"""bot/mod/dmcc/domain/__init__.py
Pure DMCC domain contracts with no Discord or provider dependencies.

Modification():

- Integrated into the production Discord bot.
"""

from .capabilities import Capability
from .errors import CapabilityUnavailable, DmccError, ServerNotFound
from .models import ManagedServer, OperationState, PowerAction, ProcessState, ServerStatus
from .registry import ServerRegistry

__all__ = [
    "Capability",
    "CapabilityUnavailable",
    "DmccError",
    "ManagedServer",
    "OperationState",
    "PowerAction",
    "ProcessState",
    "ServerNotFound",
    "ServerRegistry",
    "ServerStatus",
]
