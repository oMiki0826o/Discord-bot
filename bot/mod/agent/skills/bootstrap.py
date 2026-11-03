"""
bot/mod/agent/skills/bootstrap.py
Initialise editable Skill directory without overwriting existing files.

Modification():
- Provide safe and testable Agent module components.
"""
from __future__ import annotations
from pathlib import Path

DEFAULT_SKILL_ROOT = Path(__file__).resolve().parents[4] / "data" / "agent" / "skills"
GUIDE_NAME = "使用說明.md"
GUIDE = """# Agent Skills 使用說明

本資料夾第一次啟動時自動建立，不會覆寫既有檔案。

## 新增 Skill

建立一個小寫英文字母、數字、連字號或底線命名的目錄，例如 minecraft/，
並在裡面建立 SKILL.md：

    ---
    name: minecraft
    summary: Minecraft 技術知識搜尋指引
    when_to_use: 使用者詢問 Minecraft 技術機制時
    ---

    請先搜尋受信任的知識庫，引用實際找到的來源。

Skills 是工作指引，不會獲得額外的工具權限，也不會執行程式碼。
單份 SKILL.md 最大 128 KiB。目錄及檔案不得使用符號連結。
修改後下一次讀取會取得更新內容。不要儲存密碼或 API 金鑰。
"""


def initialize_skill_home(root: Path = DEFAULT_SKILL_ROOT) -> Path:
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    guide = folder / GUIDE_NAME
    try:
        with guide.open("x", encoding="utf-8") as handle:
            handle.write(GUIDE)
    except FileExistsError:
        return folder
    return folder
