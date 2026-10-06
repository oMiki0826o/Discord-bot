"""bot/mod/dmcc/providers/control/local_tmux.py

Modification():

- Controls one configured Minecraft server through fixed tmux argv commands.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...domain.errors import ProviderConnectionError
from ...domain.models import ProcessState


class LocalTmuxControlProvider:
    """Local tmux control with an explicit Minecraft working directory."""

    def __init__(self, provider_id: str, server_dir: str, session_name: str, start_argv: tuple[str, ...], *, timeout_seconds: float = 30.0) -> None:
        self.provider_id = provider_id
        self._server_dir = Path(server_dir)
        self._session_name = session_name
        self._start_argv = start_argv
        self._timeout_seconds = timeout_seconds

    async def status(self, target: str | None = None) -> ProcessState:
        self._validate_target(target)
        result = await self._run("has-session", "-t", self._session_name, check=False)
        if result == 0:
            return ProcessState.RUNNING
        if result == 1:
            return ProcessState.STOPPED
        raise ProviderConnectionError("tmux status command failed")

    async def start(self, target: str | None = None) -> None:
        self._validate_target(target)
        if await self.status() is ProcessState.RUNNING:
            return
        await self._run("new-session", "-d", "-s", self._session_name, "--", *self._start_argv, cwd=self._server_dir)

    async def stop(self, target: str | None = None) -> None:
        self._validate_target(target)
        if await self.status() is ProcessState.STOPPED:
            return
        await self._run("send-keys", "-t", self._session_name, "stop", "C-m")
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if await self.status() is ProcessState.STOPPED:
                return
            await asyncio.sleep(0.25)
        raise TimeoutError("Minecraft tmux session did not stop before timeout")

    async def restart(self, target: str | None = None) -> None:
        self._validate_target(target)
        await self.stop()
        await self.start()

    async def kill(self, target: str | None = None) -> None:
        self._validate_target(target)
        if await self.status() is not ProcessState.STOPPED:
            await self._run("kill-session", "-t", self._session_name)

    def _validate_target(self, target: str | None) -> None:
        if target is not None and target != self._session_name:
            raise ValueError("local_tmux control_target must match session_name")

    async def _run(self, *arguments: str, cwd: Path | None = None, check: bool = True) -> int:
        try:
            process = await asyncio.create_subprocess_exec("tmux", *arguments, cwd=str(cwd) if cwd else None, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(process.wait(), timeout=self._timeout_seconds)
        except FileNotFoundError as exc:
            raise ProviderConnectionError("tmux is not installed") from exc
        except OSError as exc:
            raise ProviderConnectionError("tmux command could not be started") from exc
        except TimeoutError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if check and process.returncode != 0:
            raise ProviderConnectionError("tmux control command failed")
        return int(process.returncode or 0)
