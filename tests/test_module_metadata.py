"""
tests/test_module_metadata.py

Modification():

- 提供 test module metadata 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from bot.core.modules.metadata import read_module_metadata


def test_metadata_reader_supports_annotated_module_dependencies(tmp_path) -> None:
    extension = tmp_path / "extension.py"
    extension.write_text(
        'MODULE_VERSION = "1.2.3"\n'
        'MODULE_DISPLAY_NAME = "Example Module"\n'
        'MODULE_DEPENDENCIES: tuple[str, ...] = ("ai", "basic")\n',
        encoding="utf-8",
    )

    metadata = read_module_metadata(extension, module_name="example")

    assert metadata.version == "1.2.3"
    assert metadata.display_name == "Example Module"
    assert metadata.dependencies == ("ai", "basic")
