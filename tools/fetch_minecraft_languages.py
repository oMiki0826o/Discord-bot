"""tools/fetch_minecraft_languages.py

Modification():

- Fetch official version-matched Minecraft language assets from Mojang HTTPS.
- Verify signed-addressed index hashes and language asset SHA-1 before atomic cache writes.
- Preserve operator custom language overrides and reject untrusted external hosts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen


_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})?")
_LOCALE = re.compile(r"[a-z]{2}_[a-z]{2}")
_HASH = re.compile(r"[0-9a-f]{40}")
_METADATA_HOSTS = frozenset({"piston-meta.mojang.com", "launchermeta.mojang.com"})
_ASSET_HOSTS = frozenset({"resources.download.minecraft.net"})


def _verified_url(url: object, hosts: frozenset[str]) -> str:
    if not isinstance(url, str):
        raise ValueError("official Mojang URL must be text")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in hosts
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443) or parts.fragment):
        raise ValueError("only official Mojang HTTPS hosts are allowed")
    return url


def _fetch(url: str, limit: int, opener) -> bytes:
    with opener(url, timeout=20) as response:
        content = response.read(limit + 1)
    if not content or len(content) > limit:
        raise ValueError("invalid official Mojang download size")
    return content


def _json(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid official Mojang JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("official Mojang JSON must be an object")
    return data


def _sha1(raw: bytes, expected: object) -> None:
    if not isinstance(expected, str) or not _HASH.fullmatch(expected):
        raise ValueError("invalid official Minecraft SHA1")
    if hashlib.sha1(raw).hexdigest() != expected:
        raise ValueError("official Minecraft checksum mismatch")


def _safe_directory(directory: Path, version: str) -> Path:
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("language cache directory must not be a symlink")
    folder = directory / "mojang" / version
    current = directory
    for name in ("mojang", version):
        current = current / name
        if current.is_symlink():
            raise ValueError("language cache path must not be a symlink")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch_official_language(
    version: str, locale: str, directory: Path, *, opener=urlopen,
) -> Path:
    """Fetch one official language into lang/mojang/<version>/<locale>.json."""
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("invalid Minecraft version")
    if not isinstance(locale, str) or not _LOCALE.fullmatch(locale):
        raise ValueError("invalid Minecraft locale")

    manifest = _json(_fetch(_MANIFEST, 8_000_000, opener))
    versions = manifest.get("versions")
    if not isinstance(versions, list):
        raise ValueError("missing official Minecraft versions")
    match = next(
        (entry for entry in versions
         if isinstance(entry, dict) and entry.get("id") == version),
        None,
    )
    if match is None:
        raise ValueError("Minecraft version not found in official manifest")
    metadata_url = _verified_url(match.get("url"), _METADATA_HOSTS)
    metadata_raw = _fetch(metadata_url, 4_000_000, opener)
    if match.get("sha1"):
        _sha1(metadata_raw, match["sha1"])
    metadata = _json(metadata_raw)

    index_info = metadata.get("assetIndex")
    if not isinstance(index_info, dict):
        raise ValueError("missing official Minecraft asset index")
    index_url = _verified_url(index_info.get("url"), _METADATA_HOSTS)
    index_raw = _fetch(index_url, 40_000_000, opener)
    _sha1(index_raw, index_info.get("sha1"))
    index = _json(index_raw)
    assets = index.get("objects")
    if not isinstance(assets, dict):
        raise ValueError("invalid official Minecraft asset entries")
    target = assets.get(f"minecraft/lang/{locale}.json")
    if not isinstance(target, dict):
        raise ValueError("Minecraft locale missing in official version assets")
    sha1 = target.get("hash")
    if not isinstance(sha1, str) or not _HASH.fullmatch(sha1):
        raise ValueError("invalid official Minecraft language checksum")
    asset_url = _verified_url(
        f"https://resources.download.minecraft.net/{sha1[:2]}/{sha1}",
        _ASSET_HOSTS,
    )
    lang_data = _fetch(asset_url, 4_000_000, opener)
    _sha1(lang_data, sha1)
    if target.get("size") != len(lang_data):
        raise ValueError("official Minecraft language asset size mismatch")
    translations = _json(lang_data)
    if (len(translations) > 50_000
            or not all(isinstance(k, str) and isinstance(v, str)
                       and len(k) <= 256 and len(v) <= 2048
                       for k, v in translations.items())):
        raise ValueError("invalid Minecraft language entries")

    folder = _safe_directory(Path(directory), version)
    out = folder / f"{locale}.json"
    if out.is_symlink():
        raise ValueError("language cache target must not be a symlink")
    descriptor, temp = tempfile.mkstemp(prefix=".mojang-lang-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(lang_data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, out)
    finally:
        Path(temp).unlink(missing_ok=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch version-verified Mojang language assets")
    parser.add_argument("--minecraft-version", required=True)
    parser.add_argument("--locale", required=True)
    parser.add_argument("--directory", type=Path, default=Path("config/minecraft-bridge/lang"))
    args = parser.parse_args()
    try:
        output = fetch_official_language(
            args.minecraft_version, args.locale, args.directory,
        )
    except (ValueError, OSError) as error:
        print(f"Language fetch failed: {error}", file=sys.stderr)
        return 1
    print(f"Verified official language saved: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
