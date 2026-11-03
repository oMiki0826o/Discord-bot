"""Discord-native, neutral usage footer. Never invent token counts."""
from __future__ import annotations
from ..runtime.models import RuntimeResult


def render_footer(result: RuntimeResult) -> str:
    model = result.model.replace("\n", " ").replace("\r", " ").replace("@", "＠")[:64] or "AI"
    usage = result.usage
    if usage is None:
        counts = "輸入 — / 輸出 — tokens"
    else:
        prefix = "約 " if usage.estimated else ""
        counts = f"{prefix}輸入 {usage.input_tokens:,} / 輸出 {usage.output_tokens:,} tokens"
        if usage.thinking_tokens:
            counts += f" · 思考 {usage.thinking_tokens:,}"
    parts = [model, counts, f"{result.elapsed_ms / 1000:.1f}s"]
    if usage is not None and not usage.estimated and result.elapsed_ms > 0 and usage.output_tokens > 0:
        # End-to-end throughput, not a claim about the model's pure decoding rate.
        parts.append(f"端到端 {usage.output_tokens / (result.elapsed_ms / 1000):.1f} tok/s")
    return "-# " + " · ".join(parts)
