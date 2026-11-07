"""tests/test_fetch_minecraft_languages.py

Modification():

- Exercise version-bound official Mojang language downloads without public network access.
- Require checksum verification, host allowlists, and no custom-language overwrite.
"""
from __future__ import annotations

import hashlib
import io
import json

import pytest

from tools.fetch_minecraft_languages import fetch_official_language


def _encoded(data):
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _fixtures():
    asset = _encoded({"death.attack.arrow": "%1$s was shot by %2$s"})
    hash_asset = hashlib.sha1(asset).hexdigest()
    index = _encoded({"objects": {
        "minecraft/lang/zh_tw.json": {"hash": hash_asset, "size": len(asset)},
    }})
    hash_index = hashlib.sha1(index).hexdigest()
    version_url = "https://piston-meta.mojang.com/v1/packages/abc/1.21.8.json"
    index_url = "https://piston-meta.mojang.com/v1/packages/abc/index.json"
    manifest = _encoded({"versions": [{"id": "1.21.8", "url": version_url}]})
    meta = _encoded({"assetIndex": {"url": index_url, "sha1": hash_index}})
    asset_url = "https://resources.download.minecraft.net/" + hash_asset[:2] + "/" + hash_asset
    return {
        "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json": manifest,
        version_url: meta,
        index_url: index,
        asset_url: asset,
    }


def test_fetches_mojang_language_by_exact_version_and_preserves_custom_override(tmp_path):
    fixtures = _fixtures()
    def fake_open(url, timeout):
        assert timeout <= 20
        return io.BytesIO(fixtures[url])
    custom = tmp_path / "zh_tw.json"
    custom.write_text('{"custom_key": "custom"}', encoding="utf-8")
    output = fetch_official_language(
        "1.21.8", "zh_tw", tmp_path, opener=fake_open,
    )
    assert output == tmp_path / "mojang" / "1.21.8" / "zh_tw.json"
    assert json.loads(output.read_text())["death.attack.arrow"]
    assert custom.read_text() == '{"custom_key": "custom"}'


def test_rejects_untrusted_manifest_urls(tmp_path):
    fixtures = _fixtures()
    base = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
    fixtures[base] = _encoded({"versions": [{
        "id": "1.21.8", "url": "https://attacker.invalid/metadata.json",
    }]})
    with pytest.raises(ValueError, match="official"):
        fetch_official_language("1.21.8", "zh_tw", tmp_path,
            opener=lambda url, timeout: io.BytesIO(fixtures[url]))


def test_rejects_tampered_asset_without_installing(tmp_path):
    fixtures = _fixtures()
    asset_url = next(url for url in fixtures if "resources.download" in url)
    fixtures[asset_url] = b'{"tampered": true}'
    with pytest.raises(ValueError, match="checksum"):
        fetch_official_language("1.21.8", "zh_tw", tmp_path,
            opener=lambda url, timeout: io.BytesIO(fixtures[url]))
    assert not (tmp_path / "mojang" / "1.21.8" / "zh_tw.json").exists()


@pytest.mark.parametrize(("version", "locale"), [
    ("../1.21.8", "zh_tw"), ("1.21.8", "../../evil"),
    ("latest", "zh_tw"), ("1.21.8", "EN-US"),
])
def test_rejects_invalid_version_or_locale(tmp_path, version, locale):
    with pytest.raises(ValueError):
        fetch_official_language(version, locale, tmp_path,
            opener=lambda *_args, **_kwargs: io.BytesIO(b"{}"))
