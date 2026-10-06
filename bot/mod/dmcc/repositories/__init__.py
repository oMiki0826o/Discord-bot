"""bot/mod/dmcc/repositories/__init__.py
JSON repository implementations owned by the DMCC module.

Modification():

- Integrated into the production Discord bot.
"""

from .links import JsonLinkRepository
from .state import JsonStateRepository

__all__ = [
    "JsonLinkRepository",
    "JsonStateRepository",
]
