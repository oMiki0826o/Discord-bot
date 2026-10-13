"""
bot/mod/ai/commands/discord.py

Modification():

- 建立 mention、`/ai` 與 Owner Prefix `$ai` 的共用 Discord adapter。
- 將 discord.py import 延後到 Cog factory，保持 domain package 可獨立匯入。
- mention 先讓 Core 通用自然語言指令判斷是否認領；`/ai` 不受影響。
- Discord 錯誤回覆前先完整記錄例外。
- 建立僅讀當前頻道的 permission-aware Channel Context adapter。
- 將 requester identity 與有上限的 reply 文字轉成 initial context。

本檔案只轉換 Discord 輸入輸出，不直接操作 Provider 或 Repository。
"""

import logging
import io
import time
import uuid
import re
from collections.abc import Callable
from typing import Any

from ..attachments.service import AttachmentInput, AttachmentType
from ..config import model_selector_choices
from ..guard import GuardBusyError, GuardRejectedError
from ..provider.models import BinaryPart
from ..provider.errors import ProviderQuotaError, ProviderTimeoutError, ProviderUnavailableError, ProviderVerificationError
from ..prompt.audit import render_prompt_audit
from ..service import AIRequest

logger = logging.getLogger("bot.mod.ai.commands")

_MODEL_SELECTORS = frozenset({"gemini", "flash", "gemma", "agent"})
_MENTION_RE = re.compile(r"<@!?(\d+)>")


def apply_model_selection(prompt: str, model: str | None) -> str:
    """Normalize a slash model selection into the natural routing directive format."""

    if model is None:
        return prompt
    selected = model.strip().casefold()
    if selected not in _MODEL_SELECTORS:
        raise ValueError("unsupported_model_selector")
    return f"model:{selected} {prompt}"


def user_error_message(error: Exception) -> str:
    """Return a stable, non-sensitive Discord message for expected AI failures."""

    if isinstance(error, GuardBusyError):
        return "已有一個 AI 請求正在處理中，請稍候再試。"
    if isinstance(error, GuardRejectedError):
        return "這個 AI 請求目前無法受理，請稍後再試。"
    if isinstance(error, ProviderVerificationError):
        return "搜尋或網址內容未能完成驗證，請稍後重試或提供其他來源。"
    if isinstance(error, ProviderQuotaError):
        return "AI 服務目前額度暫時不足，請稍後再試。"
    if isinstance(error, ProviderTimeoutError):
        return "AI 服務回應逾時，請稍後再試。"
    if isinstance(error, ProviderUnavailableError):
        return "AI 服務暫時無法使用，請稍後再試。"
    return "AI request failed. Please try again later."


def dashboard_operational_summary(data: dict[str, Any]) -> str:
    """Format aggregate-only telemetry for the owner dashboard."""

    return (
        f"Actual tokens: {int(data.get('actual_tokens', 0)):,} "
        f"({int(data.get('actual_requests', 0)):,} requests)\n"
        f"Estimated tokens: {int(data.get('estimated_tokens', 0)):,} "
        f"({int(data.get('estimated_requests', 0)):,} requests)\n"
        f"Thinking tokens: {int(data.get('thinking_tokens', 0)):,}\n"
        f"Provider errors: {int(data.get('provider_errors', 0)):,}"
    )


def prompt_status_summary(prompts: Any) -> str:
    """Format prompt source status using the loader-owned persona selection."""

    sources = prompts.load()
    return (
        "Prompt sources: "
        f"persona={prompts.active_persona()} "
        f"keywords={len(sources.keywords)} "
        f"blocked_words={len(sources.blocked_words)} "
        f"global_memory={len(sources.global_memory)}"
    )


def create_prompt_audit_sink(bot: Any, channel_id: int) -> Callable[[str, str, str], Any] | None:
    """Return an opt-in Discord owner logger; prompt content is redacted before send."""

    if channel_id <= 0:
        return None

    async def send(request_id: str, user_id: str, text: str) -> None:
        channel = bot.get_channel(channel_id)
        if channel is None:
            logger.warning("Configured AI prompt audit channel is unavailable: %s", channel_id)
            return
        rendered = render_prompt_audit(request_id, user_id, text)
        if len(rendered) <= 1_800:
            await channel.send("```text\n" + rendered.replace("```", "``\u200b`") + "\n```")
            return
        import discord
        await channel.send(file=discord.File(io.BytesIO(rendered.encode("utf-8")), filename=f"ai_prompt_{request_id}.txt"))

    return send


def should_skip_mention(prompt: str, is_claimed: Callable[[str], bool] | None) -> bool:
    """判斷 mention 是否已由 Core 的通用自然語言指令認領。"""

    return False if is_claimed is None else bool(is_claimed(prompt))


def build_initial_context(
    author: Any,
    reply: Any = None,
    *,
    text: str = "",
    bot_user_id: str = "",
    known_members: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """建立 Discord 身分與 reply 參考資料，不將其提升為 system rules。"""

    name = str(getattr(author, "display_name", "Unknown User"))[:200]
    user_id = str(getattr(author, "id", ""))
    items = [f"Requester: {name} (Discord user {user_id})"]
    if reply is not None:
        content = str(getattr(reply, "content", "")).strip()[:4_000]
        reply_author = getattr(reply, "author", None)
        if content and reply_author is not None:
            reply_name = str(getattr(reply_author, "display_name", "Unknown User"))[:200]
            reply_user_id = str(getattr(reply_author, "id", ""))
            items.append(f"Reply from {reply_name} (Discord user {reply_user_id}): {content}")
    if text:
        items.append(build_discord_identity_context(
            text,
            author_id=user_id,
            bot_user_id=bot_user_id,
            known_members=known_members,
        ))
    return tuple(items)


def build_discord_identity_context(
    text: str,
    *,
    author_id: str,
    bot_user_id: str = "",
    known_members: dict[str, str] | None = None,
) -> str:
    """Render only reliable mention mappings; never infer an unknown identity."""

    members = known_members or {}
    lines = ["Discord identity mapping (reference only):"]
    for user_id in dict.fromkeys(_MENTION_RE.findall(text)):
        if user_id == author_id:
            relation, name = "current_user", members.get(user_id, "")
        elif bot_user_id and user_id == bot_user_id:
            relation, name = "bot", ""
        elif user_id in members:
            relation, name = "member", members[user_id]
        else:
            relation, name = "unknown", ""
        lines.append(f"- id={user_id} relation={relation}" + (f" member={name}" if name else ""))
    return "\n".join(lines)


def create_channel_reader(bot: Any, *, limit: int = 30) -> Callable[[str, str, str], Any]:
    """建立安全的 current-channel reader；Agent 不會取得 bot 或 channel object。"""

    if not 1 <= limit <= 100:
        raise ValueError("channel history limit must be between 1 and 100")

    async def read_channel(user_id: str, channel_id: str, query: str) -> tuple[dict[str, str], ...]:
        try:
            resolved_user_id = int(user_id)
            resolved_channel_id = int(channel_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("channel_access_denied") from exc

        channel = bot.get_channel(resolved_channel_id)
        guild = None if channel is None else getattr(channel, "guild", None)
        member = None if guild is None else guild.get_member(resolved_user_id)
        if channel is None or member is None:
            raise ValueError("channel_access_denied")

        permissions = channel.permissions_for(member)
        if not (
            bool(getattr(permissions, "view_channel", False))
            and bool(getattr(permissions, "read_message_history", False))
        ):
            raise ValueError("channel_access_denied")

        terms = tuple(part for part in query.casefold().split() if part)
        messages: list[dict[str, str]] = []
        async for message in channel.history(limit=limit):
            content = str(getattr(message, "content", "")).strip()
            if not content:
                continue
            folded = content.casefold()
            if terms and not any(term in folded for term in terms):
                continue
            author = getattr(message, "author", None)
            created_at = getattr(message, "created_at", None)
            messages.append({
                "message_id": str(getattr(message, "id", "")),
                "author_id": str(getattr(author, "id", "")),
                "author_name": str(getattr(author, "display_name", "")),
                "content": content,
                "created_at": "" if created_at is None else created_at.isoformat(),
            })
        messages.reverse()
        return tuple(messages)

    return read_channel


def split_discord_message(text: str, *, limit: int = 1900) -> tuple[str, ...]:
    """分割 Discord 回覆並保留原文的每一個字元。"""

    if limit < 1:
        raise ValueError("limit must be positive")
    return tuple(text[index:index + limit] for index in range(0, len(text), limit)) or ("",)


async def prepare_discord_attachments(
    module: Any,
    attachments: tuple[Any, ...],
) -> tuple[tuple[str, ...], tuple[BinaryPart, ...]]:
    """Download bounded attachments and keep their text outside the user prompt."""

    module.attachments.validate_metadata(tuple(item.size for item in attachments))
    inputs: list[AttachmentInput] = []
    for item in attachments:
        inputs.append(AttachmentInput(
            item.filename,
            item.content_type or "application/octet-stream",
            await item.read(),
            item.size,
        ))
    parsed = await module.attachments.process(tuple(inputs))
    context = tuple(
        f"Attachment {item.filename} (untrusted content): {item.text or item.limitation}"
        for item in parsed
        if item.attachment_type is not AttachmentType.IMAGE
    )
    binary = tuple(
        BinaryPart(item.media_type, item.data)
        for item in parsed
        if item.attachment_type in {AttachmentType.IMAGE, AttachmentType.AUDIO, AttachmentType.VIDEO}
        and item.data
    )
    return context, binary


def create_ai_cog(
    bot: Any,
    module: Any,
    *,
    should_skip_prompt: Callable[[str], bool] | None = None,
) -> Any:
    import discord
    from discord import app_commands
    from discord.ext import commands

    model_choices = [
        app_commands.Choice(name=label, value=value)
        for label, value in model_selector_choices(module.settings)
    ]

    class AICog(commands.Cog):
        def __init__(self) -> None:
            self.bot = bot
            self.module = module
            self.module.start()

        async def cog_unload(self) -> None:
            await self.module.close()

        @app_commands.command(name="ai", description="Ask the configured AI assistant")
        @app_commands.choices(model=model_choices)
        async def ai_slash(
            self,
            interaction: discord.Interaction,
            prompt: str,
            model: str | None = None,
            attachment: discord.Attachment | None = None,
        ) -> None:
            await interaction.response.defer(thinking=True)
            try:
                selected_prompt = apply_model_selection(prompt, model)
                attachment_context, binary = await prepare_discord_attachments(
                    self.module, () if attachment is None else (attachment,),
                )
                response = await self.module.service.generate(self._request(
                    interaction.user.id,
                    interaction.channel_id,
                    interaction.guild_id,
                    str(interaction.id),
                    selected_prompt,
                    binary,
                    build_initial_context(
                        interaction.user,
                        text=selected_prompt,
                        bot_user_id=str(getattr(self.bot.user, "id", "")),
                    ),
                    attachment_context,
                ))
                for chunk in split_discord_message(response.text):
                    await interaction.followup.send(chunk, allowed_mentions=discord.AllowedMentions.none())
            except Exception as exc:
                logger.exception("AI slash request failed")
                await interaction.followup.send(user_error_message(exc), ephemeral=True)

        @commands.Cog.listener()
        async def on_message(self, message: discord.Message) -> None:
            if message.author.bot or self.bot.user is None or self.bot.user not in message.mentions:
                return
            prompt = message.content.replace(self.bot.user.mention, "").strip()
            if not prompt and not message.attachments:
                return
            if prompt and should_skip_mention(prompt, should_skip_prompt):
                return
            async with message.channel.typing():
                try:
                    attachment_context, binary = await prepare_discord_attachments(self.module, tuple(message.attachments))
                    reference = getattr(message, "reference", None)
                    reply = None if reference is None else getattr(reference, "resolved", None)
                    response = await self.module.service.generate(self._request(
                        message.author.id,
                        message.channel.id,
                        None if message.guild is None else message.guild.id,
                        str(message.id),
                        prompt or "Please analyze the attachment.",
                        binary,
                        build_initial_context(
                            message.author,
                            reply,
                            text=prompt,
                            bot_user_id=str(getattr(self.bot.user, "id", "")),
                            known_members={
                                str(member.id): str(member.display_name)
                                for member_id in _MENTION_RE.findall(prompt)
                                if message.guild is not None
                                for member in (message.guild.get_member(int(member_id)),)
                                if member is not None
                            },
                        ),
                        attachment_context,
                    ))
                    chunks = split_discord_message(response.text)
                    await message.reply(chunks[0], mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    for chunk in chunks[1:]:
                        await message.channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
                except Exception as exc:
                    logger.exception("AI mention request failed")
                    await message.reply(user_error_message(exc), mention_author=False, allowed_mentions=discord.AllowedMentions.none())

        @commands.group(name="ai", invoke_without_command=True)
        @commands.is_owner()
        async def ai_owner(self, ctx: commands.Context) -> None:
            await ctx.send("Available: status, models, quota, cache, prompt, reload, data, index, profile, persona, access, stats, diagnose, memory, history, summary")

        @ai_owner.command(name="status")
        async def ai_status(self, ctx: commands.Context) -> None:
            await ctx.send("AI module is running.")

        @ai_owner.command(name="models")
        async def ai_models(self, ctx: commands.Context) -> None:
            pools = self.module.settings.model_pools
            await ctx.send("\n".join(f"{name}: {', '.join(models)}" for name, models in pools.items()))

        @ai_owner.command(name="quota")
        async def ai_quota(self, ctx: commands.Context) -> None:
            cooldowns = self.module.provider.quota.snapshot()
            if not cooldowns:
                await ctx.send("All configured models are available.")
                return
            await ctx.send("\n".join(
                f"{model}: cooldown {seconds:.0f}s"
                for model, seconds in sorted(cooldowns.items())
            ))

        @ai_owner.command(name="cache")
        async def ai_cache(self, ctx: commands.Context) -> None:
            status = self.module.search_cache.status(now=int(time.time()))
            await ctx.send(
                "Search cache: "
                f"entries={status['entries']} expired={status['expired']} "
                f"hits={status['hits']} misses={status['misses']}"
            )

        @ai_owner.command(name="prompt")
        async def ai_prompt(self, ctx: commands.Context) -> None:
            await ctx.send(prompt_status_summary(self.module.prompts))

        @ai_owner.command(name="reload")
        async def ai_reload(self, ctx: commands.Context) -> None:
            self.module.prompts.reload()
            await ctx.send("AI prompts reloaded.")

        @ai_owner.group(name="data", invoke_without_command=True)
        @commands.is_owner()
        async def ai_data(self, ctx: commands.Context) -> None:
            await self.ai_data_sync(ctx)

        @ai_data.command(name="sync")
        @commands.is_owner()
        async def ai_data_sync(self, ctx: commands.Context) -> None:
            records, documents = await self.module.sync_owner_data()
            await ctx.send(f"Synced {records} manual memory records and indexed {documents} knowledge documents.")

        @ai_data.command(name="validate")
        @commands.is_owner()
        async def ai_data_validate(self, ctx: commands.Context) -> None:
            report = self.module.owner_data.validate()
            if not report.valid:
                await ctx.send("AI data invalid:\n" + "\n".join(f"- {item}" for item in report.issues[:10]))
                return
            await ctx.send(
                f"AI data valid: {report.manual_records} manual records, "
                f"{report.knowledge_documents} knowledge documents, "
                f"changed={report.changed_sources} removed={report.removed_sources}."
            )

        @ai_data.command(name="preview")
        @commands.is_owner()
        async def ai_data_preview(self, ctx: commands.Context) -> None:
            report = self.module.owner_data.preview()
            if not report.valid:
                await ctx.send("AI data invalid:\n" + "\n".join(f"- {item}" for item in report.issues[:10]))
                return
            await ctx.send(
                f"AI data preview: {report.manual_records} manual records would be synchronized; "
                f"{report.knowledge_documents} knowledge documents would be indexed; "
                f"changed={report.changed_sources} removed={report.removed_sources}."
            )

        @ai_owner.group(name="persona", invoke_without_command=True)
        @commands.is_owner()
        async def ai_persona(self, ctx: commands.Context) -> None:
            await ctx.send("Available: persona list, current, set <name>, save <name> <persona> || <background>, delete <name>, reload")

        @ai_persona.command(name="list")
        @commands.is_owner()
        async def ai_persona_list(self, ctx: commands.Context) -> None:
            active = self.module.prompts.active_persona()
            names = self.module.prompts.list_personas()
            if not names:
                await ctx.send("No persona profiles are available.")
                return
            await ctx.send("\n".join(f"{'* ' if name == active else '- '}{name}" for name in names))

        @ai_persona.command(name="current")
        @commands.is_owner()
        async def ai_persona_current(self, ctx: commands.Context) -> None:
            await ctx.send(f"Active persona: {self.module.prompts.active_persona()}")

        @ai_persona.command(name="set")
        @commands.is_owner()
        async def ai_persona_set(self, ctx: commands.Context, name: str) -> None:
            try:
                selected = self.module.prompts.set_active_persona(name)
            except (ValueError, LookupError, RuntimeError) as exc:
                await ctx.send(f"Persona switch failed: {exc}")
                return
            await ctx.send(f"Active persona: {selected}")

        @ai_persona.command(name="save")
        @commands.is_owner()
        async def ai_persona_save(self, ctx: commands.Context, name: str, *, content: str) -> None:
            persona, separator, background = content.partition("||")
            if not separator:
                await ctx.send("Use: $ai persona save <name> <persona text> || <background text>")
                return
            try:
                self.module.prompts.save_persona(name, persona, background)
            except (OSError, RuntimeError, ValueError) as exc:
                await ctx.send(f"Persona save failed: {exc}")
                return
            await ctx.send(f"Persona saved: {name}")

        @ai_persona.command(name="delete")
        @commands.is_owner()
        async def ai_persona_delete(self, ctx: commands.Context, name: str) -> None:
            try:
                deleted = self.module.prompts.delete_persona(name)
            except (OSError, RuntimeError, ValueError) as exc:
                await ctx.send(f"Persona delete failed: {exc}")
                return
            await ctx.send("Persona deleted." if deleted else "Persona not found.")

        @ai_persona.command(name="reload")
        @commands.is_owner()
        async def ai_persona_reload(self, ctx: commands.Context) -> None:
            self.module.prompts.reload()
            await ctx.send(f"Persona reloaded: {self.module.prompts.active_persona()}")

        @ai_owner.group(name="index", invoke_without_command=True)
        @commands.is_owner()
        async def ai_index(self, ctx: commands.Context) -> None:
            await self.ai_index_rebuild(ctx)

        @ai_index.command(name="rebuild")
        @commands.is_owner()
        async def ai_index_rebuild(self, ctx: commands.Context, full: bool = False) -> None:
            count = await self.module.rebuild_knowledge(full=full)
            mode = "full" if full else "incremental"
            await ctx.send(f"Indexed {count} changed knowledge documents ({mode}).")

        @ai_index.command(name="status")
        @commands.is_owner()
        async def ai_index_status(self, ctx: commands.Context) -> None:
            await ctx.send(str(self.module.operations.diagnose("database")))

        @ai_owner.group(name="access", invoke_without_command=True)
        @commands.is_owner()
        async def ai_access(self, ctx: commands.Context) -> None:
            await ctx.send("Available: access status <user>, ban <user> [reason], unban <user>, unrestrict <user>")

        @ai_access.command(name="status")
        @commands.is_owner()
        async def ai_access_status(self, ctx: commands.Context, user_id: str) -> None:
            state = self.module.operations.access_status(user_id)
            await ctx.send(f"{state['user_id']}: {state['state']}")

        @ai_access.command(name="ban")
        @commands.is_owner()
        async def ai_access_ban(self, ctx: commands.Context, user_id: str, *, reason: str = "") -> None:
            self.module.operations.ban(user_id, actor_id=str(ctx.author.id), reason=reason)
            await ctx.send(f"AI access banned: {user_id}")

        @ai_access.command(name="unban")
        @commands.is_owner()
        async def ai_access_unban(self, ctx: commands.Context, user_id: str) -> None:
            changed = self.module.operations.unban(user_id, actor_id=str(ctx.author.id))
            await ctx.send("AI access restored." if changed else "User is not banned.")

        @ai_access.command(name="unrestrict")
        @commands.is_owner()
        async def ai_access_unrestrict(self, ctx: commands.Context, user_id: str) -> None:
            changed = self.module.operations.unrestrict(user_id, actor_id=str(ctx.author.id))
            await ctx.send("AI restriction cleared." if changed else "User is not restricted.")

        @ai_owner.group(name="user", invoke_without_command=True)
        @commands.is_owner()
        async def ai_user(self, ctx: commands.Context) -> None:
            await ctx.send("Available: user info <user>, tier <user> <0-3>, mode <user> <normal|roleplay|creative|task|debate> [minutes]")

        @ai_user.command(name="info")
        @commands.is_owner()
        async def ai_user_info(self, ctx: commands.Context, user_id: str) -> None:
            profile = self.module.operations.user_context(user_id)
            await ctx.send("\n".join(f"{key}: {value}" for key, value in profile.items()))

        @ai_user.command(name="tier")
        @commands.is_owner()
        async def ai_user_tier(self, ctx: commands.Context, user_id: str, tier: int) -> None:
            try:
                self.module.operations.set_tier(user_id, tier, actor_id=str(ctx.author.id))
            except ValueError:
                await ctx.send("Tier must be an integer from 0 to 3.")
                return
            await ctx.send(f"AI user tier updated: {user_id} → {tier}")

        @ai_user.command(name="mode")
        @commands.is_owner()
        async def ai_user_mode(self, ctx: commands.Context, user_id: str, mode: str, minutes: int = 60) -> None:
            try:
                self.module.operations.set_mode(user_id, mode.casefold(), ttl_minutes=minutes, actor_id=str(ctx.author.id))
            except ValueError:
                await ctx.send("Mode must be normal, roleplay, creative, task, or debate; minutes must not be negative.")
                return
            await ctx.send(f"AI user mode updated: {user_id} → {mode.casefold()}")

        @ai_owner.group(name="stats", invoke_without_command=True)
        @commands.is_owner()
        async def ai_stats(self, ctx: commands.Context) -> None:
            values = self.module.operations.stats()
            await ctx.send("\n".join(f"{key}: {value}" for key, value in values.items()))

        @ai_stats.command(name="overview")
        @commands.is_owner()
        async def ai_stats_overview(self, ctx: commands.Context) -> None:
            data = self.module.operations.dashboard_snapshot()
            embed = discord.Embed(title="AI Operations Dashboard", color=discord.Color.blurple())
            embed.add_field(name="Requests (24h)", value=f"{data['requests_24h']:,}\nActive users: {data['active_users']:,}", inline=True)
            embed.add_field(name="Memory & Summary", value=f"Active memories: {data['active_memories']:,}\nSummaries: {data['summaries']:,}", inline=True)
            embed.add_field(name="Worker", value=f"Pending jobs: {data['pending_jobs']:,}", inline=True)
            embed.add_field(name="Usage (24h)", value=dashboard_operational_summary(data), inline=True)
            models = data["by_model"]
            embed.add_field(name="Models", value="\n".join(f"{name}: {count:,}" for name, count in sorted(models.items())) or "No completed requests in 24h.", inline=False)
            embed.set_footer(text="Aggregate operational data only; message and prompt content are never displayed.")
            await ctx.send(embed=embed)

        @ai_owner.group(name="diagnose", invoke_without_command=True)
        @commands.is_owner()
        async def ai_diagnose(self, ctx: commands.Context) -> None:
            await ctx.send("Available: diagnose database, memory, audit, trace <request_id>, traces [limit]")

        @ai_diagnose.command(name="database")
        @commands.is_owner()
        async def ai_diagnose_database(self, ctx: commands.Context) -> None:
            result = self.module.operations.diagnose("database")
            await ctx.send("\n".join(f"{key}: {value}" for key, value in result.items()))

        @ai_diagnose.command(name="memory")
        @commands.is_owner()
        async def ai_diagnose_memory(self, ctx: commands.Context) -> None:
            result = self.module.memory_mirror_status()
            await ctx.send("\n".join(f"{key}: {value}" for key, value in result.items()))

        @ai_diagnose.command(name="audit")
        @commands.is_owner()
        async def ai_diagnose_audit(self, ctx: commands.Context) -> None:
            entries = self.module.operations.audit()
            await ctx.send("\n".join(f"{item['action']} → {item['target_id']}" for item in entries) or "No AI operations recorded.")

        @ai_diagnose.command(name="trace")
        @commands.is_owner()
        async def ai_diagnose_trace(self, ctx: commands.Context, request_id: str) -> None:
            entries = self.module.operations.provider_trace(request_id)
            await ctx.send("\n".join(f"{item['model']}: {item['outcome']}" for item in entries) or "No provider trace for this request.")

        @ai_diagnose.command(name="traces")
        @commands.is_owner()
        async def ai_diagnose_traces(self, ctx: commands.Context, limit: int = 20) -> None:
            try:
                entries = self.module.operations.recent_provider_traces(limit=limit)
            except ValueError as exc:
                await ctx.send(str(exc))
                return
            await ctx.send("\n".join(f"{item['request_id']}: {item['model']} → {item['outcome']}" for item in entries) or "No provider traces recorded.")

        @ai_owner.group(name="memory", invoke_without_command=True)
        @commands.is_owner()
        async def ai_memory(self, ctx: commands.Context) -> None:
            await ctx.send("Available: memory list <user>, show <user> <memory_id>, forget <user> <memory_id>")

        @ai_memory.command(name="list")
        @commands.is_owner()
        async def ai_memory_list(self, ctx: commands.Context, user_id: str) -> None:
            records = self.module.operations.list_memories(user_id)
            await ctx.send("\n".join(f"{item['memory_id']} {item['status']} {item['memory_type']}.{item['memory_key']}" for item in records) or "No memories for this user.")

        @ai_memory.command(name="show")
        @commands.is_owner()
        async def ai_memory_show(self, ctx: commands.Context, user_id: str, memory_id: str) -> None:
            try:
                item = self.module.operations.show_memory(user_id, memory_id)
            except KeyError:
                await ctx.send("Memory not found for this user.")
                return
            await ctx.send("\n".join(f"{key}: {value}" for key, value in item.items()))

        @ai_memory.command(name="forget")
        @commands.is_owner()
        async def ai_memory_forget(self, ctx: commands.Context, user_id: str, memory_id: str) -> None:
            changed = self.module.operations.forget_memory(user_id, memory_id, actor_id=str(ctx.author.id))
            await ctx.send("Memory retracted." if changed else "Memory not found or already retracted.")

        @ai_memory.command(name="evidence")
        @commands.is_owner()
        async def ai_memory_evidence(self, ctx: commands.Context, user_id: str, memory_id: str) -> None:
            records = self.module.operations.memory_evidence(user_id, memory_id)
            await ctx.send("\n".join(f"{item['relation']} {item['event_id']}: {item['excerpt']}" for item in records) or "No evidence for this memory.")

        @ai_memory.command(name="export")
        @commands.is_owner()
        async def ai_memory_export(self, ctx: commands.Context, user_id: str) -> None:
            text = self.module.operations.export_memories(user_id, limit=500)
            await ctx.send(file=discord.File(io.BytesIO(text.encode("utf-8")), filename=f"ai_memory_{user_id}.md"))

        @ai_owner.group(name="global_memory", invoke_without_command=True)
        @commands.is_owner()
        async def ai_global_memory(self, ctx: commands.Context) -> None:
            await ctx.send("Available: global_memory list, set <key> <importance> <content>, remove <key>")

        @ai_global_memory.command(name="list")
        @commands.is_owner()
        async def ai_global_memory_list(self, ctx: commands.Context) -> None:
            records = self.module.global_memory.list()
            await ctx.send("\n".join(f"{item['key']} (importance={item['importance']}): {item['content']}" for item in records) or "No global memories.")

        @ai_global_memory.command(name="set")
        @commands.is_owner()
        async def ai_global_memory_set(self, ctx: commands.Context, key: str, importance: int, *, content: str) -> None:
            try:
                self.module.global_memory.upsert(key, content, importance=importance)
            except (OSError, ValueError) as exc:
                await ctx.send(f"Global memory update failed: {exc}")
                return
            await ctx.send(f"Global memory updated: {key}")

        @ai_global_memory.command(name="remove")
        @commands.is_owner()
        async def ai_global_memory_remove(self, ctx: commands.Context, key: str) -> None:
            await ctx.send("Global memory removed." if self.module.global_memory.remove(key) else "Global memory not found.")

        @ai_owner.group(name="history", invoke_without_command=True)
        @commands.is_owner()
        async def ai_history(self, ctx: commands.Context) -> None:
            await ctx.send("Available: history export <user>")

        @ai_history.command(name="export")
        @commands.is_owner()
        async def ai_history_export(self, ctx: commands.Context, user_id: str) -> None:
            text = self.module.operations.export_history(user_id)
            await ctx.send(file=discord.File(io.BytesIO(text.encode("utf-8")), filename=f"ai_history_{user_id}.md"))

        @ai_owner.group(name="summary", invoke_without_command=True)
        @commands.is_owner()
        async def ai_summary(self, ctx: commands.Context) -> None:
            await ctx.send("Available: summary show <user> <channel> <conversation>, rebuild <user> <channel> <conversation>")

        @ai_summary.command(name="show")
        @commands.is_owner()
        async def ai_summary_show(self, ctx: commands.Context, user_id: str, channel_id: str, conversation_id: str) -> None:
            summary = self.module.summaries.current(user_id, channel_id, conversation_id)
            await ctx.send(summary.content if summary is not None else "No current summary for this conversation.")

        @ai_summary.command(name="rebuild")
        @commands.is_owner()
        async def ai_summary_rebuild(self, ctx: commands.Context, user_id: str, channel_id: str, conversation_id: str) -> None:
            try:
                summary = await self.module.summaries.rebuild(user_id, channel_id, conversation_id)
            except (LookupError, RuntimeError) as exc:
                await ctx.send(f"Summary rebuild failed: {exc}")
                return
            await ctx.send(f"Summary rebuilt through {summary.last_event_id}.\n{summary.content}")

        @ai_owner.group(name="profile", invoke_without_command=True)
        async def ai_profile(self, ctx: commands.Context) -> None:
            await ctx.send("Available: profile show/set/remove")

        @ai_profile.command(name="show")
        async def ai_profile_show(self, ctx: commands.Context, member: discord.Member) -> None:
            await ctx.send(str(self.module.profiles.get(str(member.id))))

        @ai_profile.command(name="set")
        async def ai_profile_set(self, ctx: commands.Context, member: discord.Member, key: str, *, value: str) -> None:
            self.module.profiles.put(str(member.id), key, value, now=int(time.time()))
            await ctx.send("Public profile updated.")

        @ai_profile.command(name="remove")
        async def ai_profile_remove(self, ctx: commands.Context, member: discord.Member, key: str) -> None:
            removed = self.module.profiles.remove(str(member.id), key)
            await ctx.send("Public profile removed." if removed else "Public profile field not found.")

        @staticmethod
        def _request(
            user_id: int,
            channel_id: int | None,
            guild_id: int | None,
            message_id: str,
            prompt: str,
            binary: tuple[BinaryPart, ...],
            initial_context: tuple[str, ...],
            attachment_context: tuple[str, ...],
        ) -> AIRequest:
            channel = str(channel_id or 0)
            return AIRequest(
                request_id=uuid.uuid4().hex, user_id=str(user_id), channel_id=channel,
                conversation_id=f"discord:{channel}:{user_id}", message_id=message_id,
                prompt=prompt, created_at=int(time.time()), guild_id=str(guild_id or ""),
                initial_context=initial_context,
                attachment_context=attachment_context,
                binary_parts=binary,
            )

    return AICog()
