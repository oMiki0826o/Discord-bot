"""bot/mod/dmcc/protocol/auth.py

bot/mod/dmcc/dmcc/protocol/auth.py

Modification():

- 實作 DMCC Protocol v1 的 Challenge / HMAC-SHA-256 認證工具。

本檔只處理認證資料，不保存 Secret，也不處理連線狀態。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


# ── Challenge Authentication ──────────────────────


def create_challenge() -> str:
    """產生一次性的 URL-safe Challenge 字串。"""

    return secrets.token_urlsafe(32)


def create_response(challenge: str, secret: str) -> str:
    """以共享 Secret 計算 Challenge 的 HMAC-SHA-256 十六進位回應。"""

    if not isinstance(challenge, str) or not challenge:
        raise ValueError("challenge must be a non-empty string")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    return hmac.new(
        secret.encode("utf-8"),
        challenge.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_response(challenge: str, secret: str, response: str) -> bool:
    """以常數時間比較確認 peer 的 Challenge 回應。"""

    if not isinstance(response, str):
        return False
    try:
        expected = create_response(challenge, secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, response)
