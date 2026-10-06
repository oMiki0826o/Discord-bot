"""bot/mod/dmcc/domain/capabilities.py
Capabilities a configured Minecraft server can advertise.

Modification():

- Integrated into the production Discord bot.
"""

from enum import StrEnum


class Capability(StrEnum):
    BRIDGE = "bridge"
    CONTROL = "control"
    BACKUP = "backup"
    IDENTITY = "identity"
    KILL = "kill"
