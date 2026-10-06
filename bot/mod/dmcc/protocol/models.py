"""bot/mod/dmcc/protocol/models.py

bot/mod/dmcc/dmcc/protocol/models.py

Modification():

- 定義 DMCC Protocol v1 的不可變 Envelope 資料模型。
- 只描述 Python 與 Minecraft Bridge 的通訊資料，不處理編碼或網路。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# ── Protocol Model ──────────────────────


@dataclass(frozen=True, slots=True)
class Envelope:
    """One validated DMCC Protocol v1 message."""

    protocol_version: int
    type: str
    server_id: str
    request_id: str | None
    data: Mapping[str, object]
