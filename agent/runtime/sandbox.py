"""Sandbox abstraction for local execution and filesystem access."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxCommandResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class BaseSandbox:
    """Execution boundary for shell and file operations."""

    async def run_command(self, command: str, timeout: int) -> SandboxCommandResult:
        raise NotImplementedError

    def read_file(self, path: str, *, encoding: str = "utf-8") -> str:
        raise NotImplementedError

    def write_file(self, path: str, content: str, *, encoding: str = "utf-8") -> None:
        raise NotImplementedError

    def list_dir(self, path: str) -> list[Path]:
        raise NotImplementedError


class LocalSandbox(BaseSandbox):
    """Default local sandbox implementation.

    This is not strong isolation yet, but it creates a stable sandbox boundary so
    tools can be decoupled from direct OS access and later swapped for a real
    disposable execution environment.
    """

    async def run_command(self, command: str, timeout: int) -> SandboxCommandResult:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return SandboxCommandResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode,
            )
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            return SandboxCommandResult(stdout="", stderr="", exit_code=124, timed_out=True)

    def read_file(self, path: str, *, encoding: str = "utf-8") -> str:
        return Path(path).resolve().read_text(encoding=encoding, errors="replace")

    def write_file(self, path: str, content: str, *, encoding: str = "utf-8") -> None:
        resolved = Path(path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)

    def list_dir(self, path: str) -> list[Path]:
        return sorted(Path(path).resolve().iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))


import contextlib

_default_sandbox: BaseSandbox = LocalSandbox()


def get_default_sandbox() -> BaseSandbox:
    return _default_sandbox


def set_default_sandbox(sandbox: BaseSandbox) -> None:
    global _default_sandbox
    _default_sandbox = sandbox
