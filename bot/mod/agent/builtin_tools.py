"""
bot/mod/agent/builtin_tools.py
Compatibility re-export for existing integrations.
Modification():
- Preserve the old public module import while moving the implementation.
"""
from .tools.builtin import build_readonly_registry

__all__ = ("build_readonly_registry",)
