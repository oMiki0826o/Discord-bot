"""
bot/mod/ai/routing.py

Modification():

- 建立只選擇模型類別與可用能力的 Router。
- 包含他人公開個人資料的保守意圖辨識。
- 以具名文字 cue helper 保持路由判斷可讀。

本檔案不選擇 legacy/agent runtime，所有請求都走同一執行層。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_WEB_CUES = (
    "搜尋", "查詢", "找一下", "查一下", "幫我查", "幫我在網路上查", "查網頁",
    "新聞", "即時", "天氣", "股價", "匯率", "價格",
    "search", "find", "look up", "browse", "web", "news", "latest", "current",
    "weather", "stock", "price",
)
_TECHNICAL_KNOWLEDGE_CUES = (
    "什麼是", "是什麼", "怎麼做", "原理", "機制", "判定", "條件", "編碼",
    "更新抑制", "強轉", "紅石", "minecraft", "麥塊", "當機", "指令", "資料包",
    "程式碼", "源碼", "原始碼", "class", "method", "function", "api",
)

_MODEL_ALIASES = {"gemini": "gemini", "flash": "flash", "gemma": "gemma", "agent": "agent"}
_MODEL_DIRECTIVE_RE = re.compile(
    r"(?:^|[\s,，:：])(?:(?:請)?(?:切換(?:模型)?(?:到|成)?|改用|使用|用|換成)|model\s*[:：=]?)\s*(?P<model>agent|gemini|flash|gemma)(?![a-z0-9_])",
    re.IGNORECASE,
)
_MODEL_PREFIX_RE = re.compile(
    r"^\s*(?:(?:請)?(?:切換(?:模型)?(?:到|成)?|改用|使用|用|換成)|model\s*[:：=]?)\s*(?P<model>agent|gemini|flash|gemma)(?![a-z0-9_])\s*[:：,，]?\s*",
    re.IGNORECASE,
)
_BARE_MODEL_RE = re.compile(r"^\s*(?P<model>agent|gemini|flash|gemma)(?=$|[\s:：,，])\s*[:：,，]?\s*", re.IGNORECASE)


def contains_url(text: str) -> bool:
    """Return whether text contains an HTTP(S) URL suitable for Gemini URL Context."""

    return _URL_RE.search(text) is not None


class Capability(StrEnum):
    MEMORY = "memory"
    HISTORY = "history"
    TOPIC = "topic"
    KNOWLEDGE = "knowledge"
    CHANNEL_CONTEXT = "channel_context"
    SKILLS = "skills"
    WEB = "web"
    MULTIMODAL = "multimodal"
    PUBLIC_PROFILE = "public_profile"
    TIME = "time"


@dataclass(frozen=True, slots=True)
class RouteRequest:
    prompt: str
    wants_memory: bool = False
    wants_history: bool = False
    wants_topic: bool = False
    wants_knowledge: bool = False
    wants_channel_context: bool = False
    wants_skills: bool = False
    wants_web: bool = False
    has_visual_attachment: bool = False
    wants_public_profile: bool = False
    wants_time: bool = False
    model_override: str | None = None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    model_category: str
    capabilities: frozenset[Capability]


class Router:
    def __init__(self, *, default_model: str = "chat", multimodal_model: str = "vision", flash_model: str = "flash", search_model: str = "search") -> None:
        self.default_model = default_model
        self.multimodal_model = multimodal_model
        self.flash_model = flash_model
        self.search_model = search_model

    def route(self, request: RouteRequest) -> RouteDecision:
        capabilities = {Capability.KNOWLEDGE, Capability.SKILLS}
        capabilities.update({
            capability
            for enabled, capability in (
                (request.wants_memory, Capability.MEMORY),
                (request.wants_history, Capability.HISTORY),
                (request.wants_topic, Capability.TOPIC),
                (request.wants_knowledge, Capability.KNOWLEDGE),
                (request.wants_channel_context, Capability.CHANNEL_CONTEXT),
                (request.wants_skills, Capability.SKILLS),
                (request.wants_web, Capability.WEB),
                (request.has_visual_attachment, Capability.MULTIMODAL),
                (request.wants_public_profile, Capability.PUBLIC_PROFILE),
                (request.wants_time, Capability.TIME),
            )
            if enabled
        })
        selected = request.model_override
        if selected == "agent":
            selected = None
        category = {
            "gemini": self.default_model,
            "flash": self.flash_model,
            "gemma": "gemma",
        }.get(selected, self.multimodal_model if request.has_visual_attachment else self.default_model)
        if request.wants_web:
            category = self.search_model
        return RouteDecision(category, frozenset(capabilities))

    def infer(self, prompt: str, *, has_visual_attachment: bool = False) -> RouteRequest:
        """以保守關鍵詞開放能力；實際是否呼叫 Tool 仍由 Agent 決定。"""

        model_override, prompt = extract_model_directive(prompt)
        folded = prompt.casefold()
        def has_any(words: tuple[str, ...]) -> bool:
            return any(word in folded for word in words)
        return RouteRequest(
            prompt=prompt,
            wants_memory=has_any(("我喜歡", "我偏好", "remember about me", "my preference")),
            wants_history=has_any(("上次", "之前說", "昨天", "said before", "last time")),
            wants_topic=has_any(("做到哪", "進度", "current status", "project state")),
            wants_knowledge=has_any((
                "資料庫", "知識庫", "原始碼", "source code", "knowledge",
                *_TECHNICAL_KNOWLEDGE_CUES,
            )),
            wants_channel_context=has_any(("這個頻道", "大家剛剛", "this channel")),
            wants_skills=has_any(("怎麼做", "workflow", "skill")),
            wants_web=contains_url(prompt) or has_any(_WEB_CUES),
            has_visual_attachment=has_visual_attachment,
            wants_public_profile=has_any((
                "誰是", "是誰", "這個人", "怎樣的人", "怎麼樣的人", "公開資料",
                "who is", "what is this person like", "public profile",
            )),
            wants_time=has_any(("現在幾點", "現在時間", "目前時間", "幾點了", "what time", "current time", "time now")),
            model_override=model_override,
        )


def extract_model_directive(prompt: str) -> tuple[str | None, str]:
    """Extract a case-insensitive model selector and remove it from the prompt."""
    match = _MODEL_PREFIX_RE.match(prompt) or _BARE_MODEL_RE.match(prompt)
    if match is None:
        match = _MODEL_DIRECTIVE_RE.search(prompt)
        if match is None:
            return None, prompt
        cleaned = (prompt[:match.start()] + prompt[match.end():]).strip()
    else:
        cleaned = prompt[match.end():].strip()
    return _MODEL_ALIASES[match.group("model").casefold()], cleaned
