"""bot/mod/dmcc/providers/panel_http.py
Bounded, redacted HTTP transport for configured Minecraft panels.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

from collections.abc import Mapping
import json

import aiohttp

from ..domain.errors import ProviderConnectionError


class PanelHttpClient:
    """Make small JSON requests without exposing credentials or HTTP objects."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        total_timeout_seconds: float = 15.0,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("panel base_url must use http or https")
        if not api_key:
            raise ValueError("panel API key must not be empty")
        if total_timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("panel transport limits must be positive")
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self._timeout = aiohttp.ClientTimeout(total=total_timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._session: aiohttp.ClientSession | None = None

    @property
    def closed(self) -> bool:
        return self._session is None or self._session.closed

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str],
        payload: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        if not path.startswith("/") or path.startswith("//"):
            raise ProviderConnectionError("invalid panel request path")
        session = self._session
        if session is None or session.closed:
            session = aiohttp.ClientSession(timeout=self._timeout, headers=self._headers)
            self._session = session
        try:
            async with session.request(
                method,
                self._base_url + path,
                params=dict(params),
                json=dict(payload) if payload is not None else None,
            ) as response:
                if response.status >= 400:
                    if response.status in {401, 403}:
                        raise ProviderConnectionError("panel authorization failed")
                    raise ProviderConnectionError(f"panel request failed with HTTP {response.status}")
                body = await response.content.read(self._max_response_bytes + 1)
                if len(body) > self._max_response_bytes:
                    raise ProviderConnectionError("panel response exceeded configured size limit")
                try:
                    decoded = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise ProviderConnectionError("panel returned invalid JSON") from exc
                if not isinstance(decoded, Mapping):
                    raise ProviderConnectionError("panel returned a non-object JSON response")
                return dict(decoded)
        except ProviderConnectionError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ProviderConnectionError("panel connection failed") from exc

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
