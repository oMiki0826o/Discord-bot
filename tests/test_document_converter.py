"""
tests/test_document_converter.py
Modification():
- Verify shared document conversion and rejection of unsupported files.
"""
from __future__ import annotations

import asyncio

import pytest

from bot.core.documents import DocumentConverter
from bot.mod.ai.attachments.document import extract_document


def test_shared_converter_rejects_non_document_type() -> None:
    with pytest.raises(ValueError, match="Unsupported document"):
        asyncio.run(DocumentConverter.convert_bytes("payload.bin", b""))


def test_ai_document_extractor_uses_shared_converter(monkeypatch) -> None:
    async def fake_convert(cls, filename, data):
        assert filename == "example.pdf"
        assert data == b"dummy"
        return "converted Markdown"
    monkeypatch.setattr(DocumentConverter, "convert_bytes", classmethod(fake_convert))
    assert asyncio.run(extract_document("example.pdf", "application/pdf", b"dummy")) == "converted Markdown"
