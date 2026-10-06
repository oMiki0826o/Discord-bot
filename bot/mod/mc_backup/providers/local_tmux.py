"""bot/mod/mc_backup/providers/local_tmux.py

Fixed-script local tmux control; never evaluates Discord text as a shell.

Modification():

- Integrated into the production Discord bot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import BackupOperationError
from ..domain.models import ManagedBackupServer


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[tuple[str, ...], float], Awaitable[CommandResult]]


class LocalTmuxControlProvider:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        resource_dir: Path | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._runner = runner or self._run_process
        self._resource_dir = resource_dir or Path(__file__).parents[1] / "resources" / "local_control"
        self._timeout_seconds = timeout_seconds

    async def is_running(self, server: ManagedBackupServer) -> bool:
        result = await self._run("status.sh", server.tmux_session, allow_status=True)
        return result.returncode == 0

    async def start(self, server: ManagedBackupServer) -> None:
        await self._require_success("start.sh", server.tmux_session, *server.start_argv)

    async def stop(self, server: ManagedBackupServer) -> None:
        await self._require_success("stop.sh", server.tmux_session)

    async def restart(self, server: ManagedBackupServer) -> None:
        await self.stop(server)
        await self.start(server)

    async def kill(self, server: ManagedBackupServer) -> None:
        await self._require_success("stop.sh", server.tmux_session, "--kill")

    async def save(self, server: ManagedBackupServer) -> None:
        await self._require_success("save.sh", server.tmux_session)

    async def _require_success(self, script: str, *arguments: str) -> None:
        result = await self._run(script, *arguments)
        if result.returncode != 0:
            raise BackupOperationError(f"local control command failed: {script}")

    async def _run(self, script: str, *arguments: str, allow_status: bool = False) -> CommandResult:
        argv = (str(self._resource_dir / script), *arguments)
        try:
            result = await self._runner(argv, self._timeout_seconds)
        except TimeoutError as exc:
            raise BackupOperationError(f"local control command timed out: {script}") from exc
        except OSError as exc:
            raise BackupOperationError(f"local control command unavailable: {script}") from exc
        if not allow_status and result.returncode != 0:
            return result
        if allow_status and result.returncode not in (0, 1):
            raise BackupOperationError("local control status command failed")
        return result

    async def _run_process(self, argv: tuple[str, ...], timeout: float) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        return CommandResult(
            returncode=process.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
