"""
bot/mod/utility/markitdown.py

Modification():

- 提供 /markitdown Slash Command。
- 驗證附件大小並將支援的文件轉換為 Markdown。
- 使用 Worker Thread 執行同步文件轉換，避免阻塞 Discord Event Loop。
- 清理文件轉換期間建立的暫存檔案。

本檔只負責 MarkItDown 文件轉換功能，
不負責 Utility Module 的載入與其他工具功能。
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path
import tempfile

import discord
from discord import app_commands
from discord.ext import commands


logger = logging.getLogger("bot.mod.utility.markitdown")


# ── Service ──────────────────────

class MarkItDownService:
    """驗證並將單一文件轉換為 Markdown。"""

    def __init__(
        self,
        *,
        max_file_size_bytes: int,
    ) -> None:
        if max_file_size_bytes <= 0:
            raise ValueError("max_file_size_bytes 必須大於 0。")

        self.max_file_size_bytes = max_file_size_bytes

    def validate_attachment(
        self,
        *,
        filename: str,
        size: int,
    ) -> str:
        """驗證附件限制並產生輸出 Markdown 檔名。"""

        if size > self.max_file_size_bytes:
            raise ValueError("檔案大小超過允許上限。")

        stem = Path(filename).stem.strip() or "converted"
        return f"{stem}.md"

    @staticmethod
    def convert_path(
        path: Path,
    ) -> str:
        """同步將指定文件轉換為 Markdown 文字。"""

        from bot.core.documents import DocumentConverter

        return DocumentConverter.convert_path(path)


# ── Command ──────────────────────

class MarkItDownCog(commands.Cog):
    """提供附件導向的文件轉 Markdown 指令。"""

    def __init__(
        self,
        bot: commands.Bot,
        service: MarkItDownService,
    ) -> None:
        self.bot = bot
        self.service = service

    @app_commands.command(
        name="markitdown",
        description="將上傳文件轉換為 Markdown 檔案。",
    )
    @app_commands.describe(
        file="要轉換的文件。",
    )
    async def markitdown(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
    ) -> None:
        """將 Discord 附件轉換為 Markdown 並回傳檔案。"""

        try:
            output_filename = self.service.validate_attachment(
                filename=file.filename,
                size=file.size,
            )
        except ValueError as exc:
            await interaction.response.send_message(
                str(exc),
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            thinking=True,
        )

        suffix = Path(file.filename).suffix
        descriptor, temporary_name = tempfile.mkstemp(
            suffix=suffix,
        )
        os.close(descriptor)

        temporary_path = Path(temporary_name)

        try:
            await file.save(temporary_path)

            markdown = await asyncio.to_thread(
                self.service.convert_path,
                temporary_path,
            )

        except ImportError:
            logger.exception(
                "MarkItDown 套件未安裝"
            )
            await interaction.followup.send(
                "目前未安裝文件轉換所需元件。",
                ephemeral=True,
            )
            return

        except Exception:
            logger.exception(
                "文件轉換失敗 filename=%s size=%s",
                file.filename,
                file.size,
            )
            await interaction.followup.send(
                "文件轉換失敗。",
                ephemeral=True,
            )
            return

        finally:
            temporary_path.unlink(
                missing_ok=True,
            )

        if not markdown:
            await interaction.followup.send(
                "文件沒有可轉換的文字內容。",
                ephemeral=True,
            )
            return

        output = io.BytesIO(
            markdown.encode("utf-8")
        )

        await interaction.followup.send(
            file=discord.File(
                output,
                filename=output_filename,
            ),
        )
