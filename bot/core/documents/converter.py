"""
bot/core/documents/converter.py
Modification():
- Centralize MarkItDown conversion for AI attachments and Utility commands.
- Use temporary files with guaranteed cleanup and worker-thread conversion.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


class DocumentConverter:
    """Convert an already-authorized document to Markdown text."""

    @staticmethod
    def convert_path(path: Path) -> str:
        from markitdown import MarkItDown
        result = MarkItDown().convert(str(path))
        return (result.text_content or "").strip()

    @classmethod
    async def convert_bytes(cls, filename: str, data: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".docx", ".pptx", ".xlsx", ".xls"}:
            raise ValueError("Unsupported document type")
        descriptor, temporary_name = tempfile.mkstemp(suffix=suffix)
        path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            return await asyncio.to_thread(cls.convert_path, path)
        finally:
            path.unlink(missing_ok=True)
