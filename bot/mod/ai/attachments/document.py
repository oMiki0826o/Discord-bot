"""
bot/mod/ai/attachments/document.py

Modification():

- 建立 PDF、DOCX、PPTX 與試算表的可選 MarkItDown parser。
- 使用安全臨時檔並在成功或失敗後移除。

本檔案只在解析文件時懶加載可選依賴。
"""

from __future__ import annotations



async def extract_document(filename: str, media_type: str, data: bytes) -> str:
    from bot.core.documents import DocumentConverter
    return await DocumentConverter.convert_bytes(filename, data)
