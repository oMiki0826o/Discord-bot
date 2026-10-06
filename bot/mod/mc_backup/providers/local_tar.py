"""bot/mod/mc_backup/providers/local_tar.py

Validated local tar archives for standalone Minecraft server backup.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ..domain.errors import BackupOperationError
from ..domain.models import BackupArtifact, ManagedBackupServer

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")


class LocalTarBackupProvider:
    async def list(self, server: ManagedBackupServer) -> list[BackupArtifact]:
        return await asyncio.to_thread(self._list_sync, server)

    async def create(
        self, server: ManagedBackupServer, *, name: str | None = None
    ) -> BackupArtifact:
        return await asyncio.to_thread(self._create_sync, server, name)

    async def validate(self, server: ManagedBackupServer, artifact_id: str) -> BackupArtifact:
        return await asyncio.to_thread(self._validate_sync, server, artifact_id)

    async def restore(self, server: ManagedBackupServer, artifact_id: str) -> None:
        await asyncio.to_thread(self._restore_sync, server, artifact_id)

    async def delete(self, server: ManagedBackupServer, artifact_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, server, artifact_id)

    def artifact_path(self, server: ManagedBackupServer, artifact_id: str) -> Path:
        self._validate_artifact_id(artifact_id)
        return server.backup_dir / f"{artifact_id}.tar.gz"

    def _create_sync(self, server: ManagedBackupServer, name: str | None) -> BackupArtifact:
        server.backup_dir.mkdir(parents=True, exist_ok=True)
        automatic = name is None
        if name is not None and not _NAME.fullmatch(name):
            raise BackupOperationError("invalid backup name")
        prefix = "auto" if automatic else name
        artifact_id = f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
        archive = self.artifact_path(server, artifact_id)
        partial = archive.with_suffix(".tar.gz.partial")
        manifest = server.backup_dir / f"{artifact_id}.json"
        manifest_partial = manifest.with_suffix(".json.partial")
        try:
            with tarfile.open(partial, "w:gz") as output:
                for child in server.server_dir.iterdir():
                    output.add(child, arcname=child.name, recursive=True)
            sha256 = self._sha256(partial)
            size_bytes = partial.stat().st_size
            created_at = datetime.now(UTC)
            payload = {
                "artifact_id": artifact_id,
                "server_id": server.server_id,
                "created_at": created_at.isoformat(),
                "automatic": automatic,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
            manifest_partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            partial.replace(archive)
            manifest_partial.replace(manifest)
            artifact = self._artifact_from_payload(payload)
            if automatic:
                self._rotate_sync(server)
            return artifact
        except (OSError, tarfile.TarError) as exc:
            raise BackupOperationError("archive creation failed") from exc
        finally:
            partial.unlink(missing_ok=True)
            manifest_partial.unlink(missing_ok=True)

    def _list_sync(self, server: ManagedBackupServer) -> list[BackupArtifact]:
        if not server.backup_dir.exists():
            return []
        artifacts: list[BackupArtifact] = []
        for manifest in server.backup_dir.glob("*.json"):
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                artifact = self._artifact_from_payload(payload)
                if artifact.server_id == server.server_id and self.artifact_path(server, artifact.artifact_id).is_file():
                    artifacts.append(artifact)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(artifacts, key=lambda item: item.created_at, reverse=True)

    def _validate_sync(self, server: ManagedBackupServer, artifact_id: str) -> BackupArtifact:
        archive = self.artifact_path(server, artifact_id)
        manifest = server.backup_dir / f"{artifact_id}.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            artifact = self._artifact_from_payload(payload)
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BackupOperationError("backup manifest is invalid") from exc
        if artifact.artifact_id != artifact_id or artifact.server_id != server.server_id:
            raise BackupOperationError("backup manifest does not match requested server")
        if not archive.is_file() or archive.stat().st_size != artifact.size_bytes:
            raise BackupOperationError("backup archive is missing or changed")
        if self._sha256(archive) != artifact.sha256:
            raise BackupOperationError("backup archive checksum mismatch")
        try:
            with tarfile.open(archive, "r:gz") as source:
                for member in source.getmembers():
                    self._validate_member(member)
        except (OSError, tarfile.TarError) as exc:
            raise BackupOperationError("backup archive is invalid") from exc
        return artifact

    def _restore_sync(self, server: ManagedBackupServer, artifact_id: str) -> None:
        self._validate_sync(server, artifact_id)
        archive = self.artifact_path(server, artifact_id)
        stage = server.server_dir.parent / f".{server.server_dir.name}.restore-{uuid.uuid4().hex}"
        rollback = server.server_dir.parent / f".{server.server_dir.name}.rollback-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            with tarfile.open(archive, "r:gz") as source:
                members = source.getmembers()
                for member in members:
                    self._validate_member(member)
                source.extractall(stage, members=members)
            server.server_dir.replace(rollback)
            try:
                stage.replace(server.server_dir)
            except OSError:
                rollback.replace(server.server_dir)
                raise
            shutil.rmtree(rollback)
        except (OSError, tarfile.TarError) as exc:
            raise BackupOperationError("backup restore failed") from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    def _delete_sync(self, server: ManagedBackupServer, artifact_id: str) -> None:
        self._validate_artifact_id(artifact_id)
        self.artifact_path(server, artifact_id).unlink(missing_ok=True)
        (server.backup_dir / f"{artifact_id}.json").unlink(missing_ok=True)

    def _rotate_sync(self, server: ManagedBackupServer) -> None:
        automatic = [artifact for artifact in self._list_sync(server) if artifact.automatic]
        for artifact in automatic[server.keep_automatic :]:
            self._delete_sync(server, artifact.artifact_id)

    @staticmethod
    def _validate_member(member: tarfile.TarInfo) -> None:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or member.isdev():
            raise BackupOperationError("unsafe archive member")

    @staticmethod
    def _validate_artifact_id(artifact_id: str) -> None:
        if not _NAME.fullmatch(artifact_id):
            raise BackupOperationError("invalid backup artifact")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _artifact_from_payload(payload: Any) -> BackupArtifact:
        if not isinstance(payload, dict):
            raise ValueError("manifest must be an object")
        return BackupArtifact(
            artifact_id=str(payload["artifact_id"]),
            server_id=str(payload["server_id"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            automatic=bool(payload["automatic"]),
            size_bytes=int(payload["size_bytes"]),
            sha256=str(payload["sha256"]),
        )
