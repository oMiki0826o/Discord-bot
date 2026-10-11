"""
bot/mod/ai/service.py

Modification():

- 建立 Discord 入口共用的唯一 AI 生成服務。
- 串接 Guard、Event Store、Context、Prompt、Router、Active Runtime 與 Memory Job。
- 將 Discord identity、reply 與附件文字作為不可信任 initial context。
- 依基礎 Router 決定交由 Context Planner 查詢的資料來源。

本檔案不依賴 Discord 或 Gemini SDK，是 AI Module 的 application boundary。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from opencc import OpenCC

from .config import AiSettings
from .context.models import ContextRequest
from .history.models import EventRole, NewEvent
from .provider.models import BinaryPart
from .routing import RouteRequest
from .runtime.models import RuntimeRequest, RuntimeResult
from .runtime.protocol import AiRuntime
from .prompt.audit import redact_prompt

logger = logging.getLogger("bot.mod.ai.audit")

_LEADING_PERSONA_INTRO = re.compile(
    r"^(?:(?:您好|你好)[，,!！\s]*)?(?:我是)?流螢[。！!,，\s]*"
)
_LEADING_TOOL_REPORT = re.compile(
    r"^(?:這是|以下是)?我在(?:檢索|搜尋|查詢|查找|讀取)[^。！？\n]{0,500}[。！？]\s*"
)
_FENCED_CODE = re.compile(r"```[\s\S]*?(?:```|\Z)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_TO_TAIWAN_TRADITIONAL = OpenCC("s2twp")


def _convert_prose_to_taiwan_traditional(text: str) -> str:
    """Convert prose while preserving fenced and inline code verbatim."""

    def convert_inline(value: str) -> str:
        parts: list[str] = []
        cursor = 0
        for match in _INLINE_CODE.finditer(value):
            parts.append(_TO_TAIWAN_TRADITIONAL.convert(value[cursor:match.start()]))
            parts.append(match.group(0))
            cursor = match.end()
        parts.append(_TO_TAIWAN_TRADITIONAL.convert(value[cursor:]))
        return "".join(parts)

    parts: list[str] = []
    cursor = 0
    for match in _FENCED_CODE.finditer(text):
        parts.append(convert_inline(text[cursor:match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(convert_inline(text[cursor:]))
    return "".join(parts)


def normalize_reply_text(text: str) -> str:
    """Remove transport artefacts without rewriting a model's actual answer."""

    normalized = text.strip()
    # A function-call response can occasionally surface a closing structural
    # delimiter before the first text part.  It is never meaningful prose at
    # the start of a Discord reply.
    normalized = normalized.lstrip("}]}）〉").lstrip()
    # Persona-only greetings and tool-process reports add no answer value and
    # make a normal Discord reply read like a service script.  Only strip them
    # at the very beginning, leaving all substantive technical content intact.
    normalized = _convert_prose_to_taiwan_traditional(normalized)
    normalized = _LEADING_PERSONA_INTRO.sub("", normalized)
    normalized = _LEADING_TOOL_REPORT.sub("", normalized)
    return normalized.strip()


def render_user_context(profile: dict[str, Any]) -> str:
    """Render the small, trusted owner-managed user state as reference context."""

    tier = int(profile.get("tier", 0))
    tier_name = str(profile.get("tier_name", "陌生人"))[:80]
    interactions = max(0, int(profile.get("interaction_count", 0)))
    mode = str(profile.get("mode", "normal"))[:80]
    mode_label = str(profile.get("mode_label", "一般對話"))[:80]
    relationship = str(profile.get("relationship", "standard"))
    relationship_context = (
        ", relationship=important_person"
        if relationship == "important_person"
        else ""
    )
    return (
        "Requester AI profile (reference only): "
        f"tier={tier} ({tier_name}), interactions={interactions}, "
        f"mode={mode} ({mode_label}){relationship_context}"
    )


@dataclass(frozen=True, slots=True)
class AIRequest:
    request_id: str
    user_id: str
    channel_id: str
    conversation_id: str
    message_id: str | None
    prompt: str
    created_at: int
    guild_id: str = ""
    route: RouteRequest | None = None
    initial_context: tuple[str, ...] = ()
    attachment_context: tuple[str, ...] = ()
    binary_parts: tuple[BinaryPart, ...] = ()

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.request_id, self.user_id, self.channel_id, self.conversation_id, self.prompt)):
            raise ValueError("AI request identity and prompt must not be blank")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative")


@dataclass(frozen=True, slots=True)
class AIResponse:
    text: str
    model: str
    request_id: str
    assistant_event_id: str
    runtime: RuntimeResult


class AIService:
    def __init__(self, *, settings: AiSettings, events: Any, context: Any, context_planner: Any, prompts: Any, composer: Any, router: Any, guard: Any, runtime: AiRuntime, memory_jobs: Any, audit_sink: Callable[[str, str, str], Awaitable[None]] | None = None, user_context_provider: Callable[[str], dict[str, Any]] | None = None, interaction_recorder: Callable[[str], int] | None = None) -> None:
        self.settings = settings
        self.events = events
        self.context = context
        self.context_planner = context_planner
        self.prompts = prompts
        self.composer = composer
        self.router = router
        self.guard = guard
        self.runtime = runtime
        self.memory_jobs = memory_jobs
        self.audit_sink = audit_sink
        self.user_context_provider = user_context_provider
        self.interaction_recorder = interaction_recorder

    async def generate(self, request: AIRequest) -> AIResponse:
        from dataclasses import replace
        from .routing import extract_model_directive

        _model, cleaned_prompt = extract_model_directive(request.prompt)
        if not cleaned_prompt:
            cleaned_prompt = request.prompt
        if cleaned_prompt != request.prompt:
            route = request.route
            if route is None:
                route = self.router.infer(cleaned_prompt, has_visual_attachment=bool(request.binary_parts))
            if _model:
                route = replace(route, model_override=_model)
            request = replace(request, prompt=cleaned_prompt, route=route)
        permit = await self.guard.acquire(request.user_id, prompt=request.prompt)
        try:
            user_event_id = f"{request.request_id}:user"
            self.events.append(NewEvent(user_event_id, request.user_id, request.channel_id, request.message_id, request.conversation_id, EventRole.USER, request.prompt, request.created_at, {"guild_id": request.guild_id}))
            decision = self.router.route(request.route or self.router.infer(request.prompt, has_visual_attachment=bool(request.binary_parts)))
            is_gemma = decision.model_category == "gemma"
            context_request = ContextRequest(
                user_id=request.user_id,
                channel_id=request.channel_id,
                conversation_id=request.conversation_id,
                current_event_id=user_event_id,
                max_tokens=min(self.settings.context_max_tokens, 1_000) if is_gemma else self.settings.context_max_tokens,
                recent_limit=min(self.settings.recent_message_limit, 4) if is_gemma else self.settings.recent_message_limit,
                include_memory=False,
                include_topics=False,
            )
            context_pack = await self.context_planner.build(
                context_request,
                prompt=request.prompt,
                route=request.route or self.router.infer(request.prompt, has_visual_attachment=bool(request.binary_parts)),
                initial_context=(
                    request.initial_context
                    + (() if self.user_context_provider is None else (render_user_context(self.user_context_provider(request.user_id)),))
                    + request.attachment_context
                ),
            )
            bundle = self.composer.compose(
                sources=self.prompts.load(),
                context=context_pack,
                conversation=tuple(),
                current_message=request.prompt,
                compact=is_gemma,
            )
            audit_text = redact_prompt(bundle.system_instruction + "\nCurrent request: " + request.prompt)
            logger.debug(
                "AI prompt audit prepared request=%s user=%s chars=%d context_blocks=%d",
                request.request_id,
                request.user_id,
                len(audit_text),
                len(bundle.context_blocks),
            )
            if self.audit_sink is not None:
                try:
                    await self.audit_sink(request.request_id, request.user_id, audit_text)
                except Exception:
                    logger.exception("AI prompt audit delivery failed request=%s", request.request_id)
            candidates = self.settings.model_pools.get(decision.model_category, self.settings.model_pools["chat"])
            result = await self.runtime.run(RuntimeRequest(
                request_id=request.request_id,
                user_id=request.user_id,
                channel_id=request.channel_id,
                guild_id=request.guild_id,
                prompt=request.prompt,
                system_instruction=bundle.system_instruction,
                context_blocks=tuple(block.content for block in bundle.context_blocks),
                binary_parts=request.binary_parts,
                model_candidates=tuple(candidates),
                capabilities=frozenset(item.value for item in decision.capabilities),
            ))
            text = normalize_reply_text(result.text)
            if not text:
                raise RuntimeError("Agent returned an empty response")
            assistant_event_id = f"{request.request_id}:assistant"
            self.events.append(NewEvent(assistant_event_id, request.user_id, request.channel_id, None, request.conversation_id, EventRole.ASSISTANT, text, request.created_at + 1, {"model": result.model}))
            try:
                self.memory_jobs.enqueue(user_event_id, now=request.created_at)
            except Exception:
                logger.exception(
                    "AI memory job enqueue failed request=%s event=%s",
                    request.request_id,
                    user_event_id,
                )
            if self.interaction_recorder is not None:
                try:
                    self.interaction_recorder(request.user_id)
                except Exception:
                    logger.exception(
                        "AI interaction record failed request=%s user=%s",
                        request.request_id,
                        request.user_id,
                    )
        except BaseException:
            permit.release(success=False)
            raise
        permit.release(success=True)
        return AIResponse(text, result.model, request.request_id, assistant_event_id, result)

    async def close(self) -> None:
        close = getattr(self.runtime, "close", None)
        if close is not None:
            await close()
        self.guard.clear()
