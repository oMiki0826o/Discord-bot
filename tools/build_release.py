"""
tools/build_release.py

Modification():

- 建立可直接發布的乾淨 ZIP。
- 排除 Secret、Runtime data、虛擬環境、Git metadata 與 cache。
- 排除僅供維護端使用的 tools/。
- 固定 ZIP 內容順序與時間戳，讓相同原始碼可產生可重現的封裝。

本工具只複製發布需要的檔案，不修改工作目錄內容。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import argparse
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = PROJECT_ROOT / "VERSION"
DEFAULT_DIST_DIR = PROJECT_ROOT / "dist"

_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".github-cache",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".venv",
        ".vscode",
        "__MACOSX",
        "__pycache__",
        "data",
        "dist",
        "htmlcov",
        "logs",
        "tools",
        "venv",
    }
)
_EXCLUDED_FILE_NAMES = frozenset(
    {
        ".coverage",
        ".DS_Store",
        ".env",
        ".env.local",
        "Thumbs.db",
        "output.txt",
    }
)
_EXCLUDED_SUFFIXES = frozenset({".db", ".log", ".pyc", ".pyo"})
_ALLOWED_TOP_LEVEL = frozenset({
    ".env.example",
    ".github",
    ".gitignore",
    "LICENSE",
    "README.md",
    "VERSION",
    "bot",
    "bridge",
    "docs",
    "main.py",
    "requirements-dev.txt",
    "requirements-lock.txt",
    "requirements.txt",
    "ruff.toml",
    "settings",
    "tests",
})


def read_version() -> str:
    """讀取並驗證專案版本字串。"""

    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version or any(character.isspace() for character in version):
        raise RuntimeError("VERSION 必須是單行且不可為空")
    return version


def should_include(relative: Path) -> bool:
    """判斷工作目錄內的檔案是否允許進入公開發布包。"""

    if not relative.parts or relative.parts[0] not in _ALLOWED_TOP_LEVEL:
        return False
    if any(part in _EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1]):
        return False
    if relative.name in _EXCLUDED_FILE_NAMES:
        return False
    if relative.name.startswith(".env.") and relative.name != ".env.example":
        return False
    if relative.parts[:2] == ("docs", "superpowers"):
        return False
    if relative.suffix.casefold() in _EXCLUDED_SUFFIXES:
        return False
    if relative.parts[:1] == ("settings",) and relative.suffix.casefold() == ".json":
        return False
    return True


def release_files(project_root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    """取得排序後的發布檔案清單。"""

    root = project_root.resolve(strict=True)
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if not path.is_symlink()
        and path.is_file()
        and path.resolve(strict=True).is_relative_to(root)
        and should_include(path.relative_to(root))
    )


def _zip_info(archive_name: str, mode: int) -> zipfile.ZipInfo:
    """建立固定 metadata 的 ZIP entry。"""

    info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def build_release(output: Path | None = None) -> Path:
    """建立發布 ZIP 並回傳輸出路徑。"""

    version = read_version()
    root_name = f"Discord-Bot-v{version}"
    target = output or (DEFAULT_DIST_DIR / f"{root_name}.zip")
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    files = release_files()
    if not files:
        raise RuntimeError("找不到可發布檔案")

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(PROJECT_ROOT)
            archive_name = PurePosixPath(root_name, *relative.parts).as_posix()
            mode = path.stat().st_mode
            archive.writestr(_zip_info(archive_name, mode), path.read_bytes())

    return target


def main() -> None:
    """Command-line entry point。"""

    parser = argparse.ArgumentParser(description="建立 Discord Bot 正式發布 ZIP")
    parser.add_argument(
        "--output",
        type=Path,
        help="自訂輸出 ZIP 路徑；未指定時使用 dist/Discord-Bot-v<version>.zip",
    )
    args = parser.parse_args()
    output = build_release(args.output)
    print(output)


if __name__ == "__main__":
    main()
