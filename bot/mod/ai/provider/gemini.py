"""
bot/mod/ai/provider/gemini.py

Modification():

- 建立 google-genai 的懶加載 Transport adapter。
- 將 SDK 錯誤與 function calls 轉成 Module-owned 契約。
- 防止 Gemini built-in tools 與 Agent Function Calling 同一請求衝突。
- 讓 Gemini 3 相容模型以 tool-context circulation 組合搜尋與函式工具。

本檔案是 AI Module 唯一直接理解 Gemini SDK 的位置。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from .errors import ProviderError, ProviderQuotaError, ProviderUnavailableError
from .models import GenerationRequest, ProviderObservation, ProviderResponse, ProviderToolCall

_RETRY_RE = re.compile(r"(?:retryDelay|retry in)[^0-9]*(\d+(?:\.\d+)?)", re.IGNORECASE)


def inspect_response_observation(
    response: Any,
    *,
    requested_web: bool,
    requested_url_context: bool,
) -> ProviderObservation:
    """Read SDK metadata defensively without coupling the runtime to SDK classes.

    Google Search grounding is valid only when it contains at least one returned
    grounding chunk. URL Context is valid only for explicit success statuses.
    A tool that was not requested needs no corresponding metadata.
    """

    grounded = not requested_web or _has_grounding_chunk(response)
    url_context_succeeded = not requested_url_context or _has_successful_url_context(response)
    return ProviderObservation(grounded=grounded, url_context_succeeded=url_context_succeeded)


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _has_grounding_chunk(response: Any) -> bool:
    candidates = _read(response, "candidates", ()) or ()
    metadata_values = [_read(response, "grounding_metadata")]
    metadata_values.extend(_read(candidate, "grounding_metadata") for candidate in candidates)
    for metadata in metadata_values:
        chunks = _read(metadata, "grounding_chunks", ()) or ()
        if any(_read(chunk, "web") is not None or _read(chunk, "retrieved_context") is not None for chunk in chunks):
            return True
    return False


def _has_successful_url_context(response: Any) -> bool:
    metadata_values = [_read(response, "url_context_metadata")]
    candidates = _read(response, "candidates", ()) or ()
    metadata_values.extend(_read(candidate, "url_context_metadata") for candidate in candidates)
    for metadata in metadata_values:
        for item in (_read(metadata, "url_metadata", ()) or ()):
            status = str(_read(item, "url_retrieval_status", "")).upper()
            if status.endswith("SUCCESS"):
                return True
    return False


class GeminiTransport:
    def __init__(self, api_key: str, *, client: Any = None) -> None:
        if not api_key.strip() and client is None:
            raise ValueError("GEMINI_API is required")
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self.client = client

    async def generate(self, request: GenerationRequest, model: str) -> ProviderResponse:
        try:
            config: dict[str, Any] = {
                "system_instruction": request.system_instruction,
                "max_output_tokens": request.max_output_tokens,
                # AgentRuntime owns the tool loop; SDK AFC must not execute
                # functions behind our back or create an extra model turn.
                "automatic_function_calling": {"disable": True},
            }
            tools = _build_tools(request)
            if tools:
                config["tools"] = tools
            if request.allow_combined_tools:
                config["tool_config"] = {"include_server_side_tool_invocations": True}
            contents: Any = request.prompt
            if request.binary_parts or request.transcript:
                from google.genai import types
                user_parts = [types.Part.from_text(text=request.prompt)] + [types.Part.from_bytes(data=part.data, mime_type=part.media_type) for part in request.binary_parts]
                contents = [types.Content(role="user", parts=user_parts)]
                for entry in request.transcript:
                    if entry.get("role") == "model":
                        provider_content = entry.get("provider_content")
                        if provider_content is not None:
                            contents.append(provider_content)
                        else:
                            parts = [
                                _function_call_part(types, call)
                                for call in entry.get("function_calls", ())
                            ]
                            contents.append(types.Content(role="model", parts=parts))
                    elif entry.get("role") == "tool":
                        parts = [
                            types.Part(function_response=types.FunctionResponse(
                                name=call.name,
                                id=call.call_id or None,
                                response={"ok": result.ok, "data": result.data, "error": result.error},
                            ))
                            for call, result in entry.get("results", ())
                        ]
                        contents.append(types.Content(role="user", parts=parts))
            response = await self.client.aio.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:
            raise self._translate_error(exc) from exc
        calls = tuple(_provider_tool_call(part) for part in _function_call_parts(response))
        try:
            text = str(response.text or "")
        except (AttributeError, ValueError):
            text = ""
        return ProviderResponse(
            text,
            model,
            calls,
            response,
            _candidate_content(response),
            inspect_response_observation(
                response,
                requested_web=request.use_web,
                requested_url_context=request.use_url_context,
            ),
        )

    async def stream(self, request: GenerationRequest, model: str) -> AsyncIterator[str]:
        """Yield native SDK text chunks for callers that opt into streamed delivery."""

        try:
            config: dict[str, Any] = {
                "system_instruction": request.system_instruction,
                "max_output_tokens": request.max_output_tokens,
                "automatic_function_calling": {"disable": True},
            }
            tools = _build_tools(request)
            if tools:
                config["tools"] = tools
            if request.allow_combined_tools:
                config["tool_config"] = {"include_server_side_tool_invocations": True}
            contents: Any = request.prompt
            if request.binary_parts:
                from google.genai import types
                contents = [types.Content(role="user", parts=[types.Part.from_text(text=request.prompt)] + [types.Part.from_bytes(data=part.data, mime_type=part.media_type) for part in request.binary_parts])]
            stream = self.client.aio.models.generate_content_stream(model=model, contents=contents, config=config)
            async for response in stream:
                try:
                    text = str(response.text or "")
                except (AttributeError, ValueError):
                    text = ""
                if text:
                    yield text
        except Exception as exc:
            raise self._translate_error(exc) from exc

    async def close(self) -> None:
        aio = getattr(self.client, "aio", None)
        close = getattr(aio, "aclose", None)
        if close is not None:
            await close()
            return
        close = getattr(self.client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    @staticmethod
    def _translate_error(error: Exception) -> ProviderError:
        text = str(error)
        code = getattr(error, "code", None)
        if code == 429 or "429" in text or "RESOURCE_EXHAUSTED" in text.upper():
            match = _RETRY_RE.search(text)
            retry = None if match is None else max(0, round(float(match.group(1))))
            return ProviderQuotaError(text, retry_after_seconds=retry)
        if code in {408, 500, 502, 503, 504} or any(
            token in text.upper()
            for token in ("TIMEOUT", "UNAVAILABLE", "503", "CANNOT CONNECT", "NODENAME NOR SERVNAME", "DNS")
        ):
            return ProviderUnavailableError(text)
        return ProviderError(text)


# ── Tool Configuration ──────────────────────

def _build_tools(request: GenerationRequest) -> list[dict[str, Any]]:
    """Build a Gemini-compatible tool set for one provider request.

    Gemini 2.x rejects built-in Google tools and function declarations in the
    same request.  Gemini 3 supports their combination only when the request
    explicitly enables server-side tool context circulation.
    """

    if request.tools:
        if request.allow_combined_tools:
            tool: dict[str, Any] = {"function_declarations": list(request.tools)}
            if request.use_web:
                tool["google_search"] = {}
            if request.use_url_context:
                tool["url_context"] = {}
            return [tool]
        return [{"function_declarations": list(request.tools)}]
    tools: list[dict[str, Any]] = []
    if request.use_web:
        tools.append({"google_search": {}})
    if request.use_url_context:
        tools.append({"url_context": {}})
    return tools


def _function_call_parts(response: Any) -> tuple[Any, ...]:
    """Return original SDK parts so Gemini thought signatures are not lost."""

    candidates = _read(response, "candidates", ()) or ()
    parts: list[Any] = []
    for candidate in candidates:
        content = _read(candidate, "content")
        for part in (_read(content, "parts", ()) or ()):
            if _read(part, "function_call") is not None:
                parts.append(part)
    return tuple(parts)


def _candidate_content(response: Any) -> Any:
    candidates = _read(response, "candidates", ()) or ()
    return _read(candidates[0], "content") if candidates else None


def _provider_tool_call(part: Any) -> ProviderToolCall:
    call = _read(part, "function_call")
    return ProviderToolCall(
        str(_read(call, "name", "")),
        dict(_read(call, "args", {}) or {}),
        _read(part, "thought_signature"),
        str(_read(call, "id", "") or ""),
    )


def _function_call_part(types: Any, call: Any) -> Any:
    """Recreate a model function-call part without stripping its signature."""

    part = types.Part(function_call=types.FunctionCall(
        name=call.name,
        args=call.arguments,
        id=call.call_id or None,
    ))
    signature = getattr(call, "thought_signature", None)
    if signature is not None:
        part.thought_signature = signature
    return part
