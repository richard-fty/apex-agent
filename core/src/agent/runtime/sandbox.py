"""Sandbox abstraction for local execution and filesystem access."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import tempfile
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import settings


@dataclass
class SandboxCommandResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class BaseSandbox:
    """Execution boundary for shell and file operations.

    Implementations must expose a stable provision/destroy lifecycle so sessions
    can own a disposable execution environment (Gap 4).
    """

    async def provision(self, resources: dict[str, Any] | None = None) -> None:
        """Allocate the sandbox environment. No-op for implementations that need none."""

    async def destroy(self) -> None:
        """Tear down and discard the sandbox environment."""

    async def run_command(self, command: str, timeout: int) -> SandboxCommandResult:
        raise NotImplementedError

    async def run_oneshot(
        self,
        command: str,
        timeout: int,
        *,
        network: str = "none",
    ) -> SandboxCommandResult:
        return await self.run_command(command, timeout)

    def read_file(self, path: str, *, encoding: str = "utf-8") -> str:
        raise NotImplementedError

    def write_file(self, path: str, content: str, *, encoding: str = "utf-8") -> None:
        raise NotImplementedError

    def list_dir(self, path: str) -> list[Path]:
        raise NotImplementedError


@dataclass(frozen=True)
class SandboxMount:
    source: str
    target: str
    read_only: bool = False


class LocalSandbox(BaseSandbox):
    """Provisioned local sandbox with a disposable HOME and scrubbed env.

    This preserves access to host binaries and the checked-out workspace while
    avoiding direct credential passthrough to child processes.
    """

    def __init__(
        self,
        *,
        workspace_root: str | None = None,
        env_allowlist: set[str] | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.env_allowlist = env_allowlist or {"PATH", "LANG", "LC_ALL", "TERM"}
        self._home_dir: tempfile.TemporaryDirectory[str] | None = None

    async def provision(self, resources: dict[str, Any] | None = None) -> None:
        if self._home_dir is None:
            self._home_dir = tempfile.TemporaryDirectory(prefix="apex-sandbox-")

    async def destroy(self) -> None:
        if self._home_dir is not None:
            self._home_dir.cleanup()
            self._home_dir = None

    @property
    def home_dir(self) -> str | None:
        return None if self._home_dir is None else self._home_dir.name

    def _command_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in self.env_allowlist:
            value = os.environ.get(key)
            if value:
                env[key] = value
        env["PATH"] = env.get("PATH", os.environ.get("PATH", ""))
        env["HOME"] = self.home_dir or str(self.workspace_root)
        env["PWD"] = str(self.workspace_root)
        return env

    async def run_command(self, command: str, timeout: int) -> SandboxCommandResult:
        await self.provision()
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_root),
            env=self._command_env(),
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

    async def run_oneshot(
        self,
        command: str,
        timeout: int,
        *,
        network: str = "none",
    ) -> SandboxCommandResult:
        # Local fallback cannot enforce network boundaries; it still runs with
        # the same scrubbed environment and disposable HOME as run_command.
        return await self.run_command(command, timeout)

    def read_file(self, path: str, *, encoding: str = "utf-8") -> str:
        return Path(path).resolve().read_text(encoding=encoding, errors="replace")

    def write_file(self, path: str, content: str, *, encoding: str = "utf-8") -> None:
        resolved = Path(path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)

    def list_dir(self, path: str) -> list[Path]:
        return sorted(
            Path(path).resolve().iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )


class DockerSandbox(BaseSandbox):
    """Container-backed sandbox with per-session isolation.

    Each DockerSandbox instance owns exactly one container. Credentials
    are kept outside by never forwarding host environment variables.
    Call ``provision()`` before use and ``destroy()`` when done.

    Gap 4: satisfies sandbox_disposable_per_session and
    sandbox_credential_isolation requirements.
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        work_dir: str = "/workspace",
        network: str = "none",
        mounts: list[SandboxMount] | None = None,
    ) -> None:
        self.image = image
        self.work_dir = work_dir
        self.network = network
        self.mounts = list(mounts or [])
        self._container_id: str | None = None

    async def provision(self, resources: dict[str, Any] | None = None) -> None:
        """Create a fresh Docker container for this session."""
        if self._container_id is not None:
            return
        res = resources or {}
        memory = res.get("memory", "256m")
        cpus = str(res.get("cpus", "0.5"))
        argv = [
            "docker", "run", "-d", "--rm",
            "--memory", memory,
            "--cpus", cpus,
            "--network", self.network,
            "--workdir", self.work_dir,
            "--env", f"HOME={self.work_dir}",
            # Do NOT forward any host env vars — credential isolation.
            "--env-file", "/dev/null",
        ]
        for mount in self.mounts:
            mode = "ro" if mount.read_only else "rw"
            argv.extend(["-v", f"{mount.source}:{mount.target}:{mode}"])
        argv.extend([self.image, "sleep", "infinity"])
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"DockerSandbox.provision() failed: {stderr.decode().strip()}"
            )
        self._container_id = stdout.decode().strip()

    async def destroy(self) -> None:
        """Kill and remove the container."""
        if self._container_id is None:
            return
        cid = self._container_id
        self._container_id = None
        proc = await asyncio.create_subprocess_exec(
            "docker", "kill", cid,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    def _assert_provisioned(self) -> str:
        if self._container_id is None:
            raise RuntimeError(
                "DockerSandbox not provisioned. Call await sandbox.provision() first."
            )
        return self._container_id

    async def run_command(self, command: str, timeout: int) -> SandboxCommandResult:
        cid = self._assert_provisioned()
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", cid, "sh", "-c", command,
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
            with contextlib.suppress(Exception):
                proc.kill()
            return SandboxCommandResult(stdout="", stderr="", exit_code=124, timed_out=True)

    async def run_oneshot(
        self,
        command: str,
        timeout: int,
        *,
        network: str = "none",
    ) -> SandboxCommandResult:
        argv = [
            "docker", "run", "--rm",
            "--memory", "1g",
            "--cpus", "1",
            "--network", network,
            "--workdir", self.work_dir,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", f"HOME={self.work_dir}",
            "--env", "PNPM_STORE_DIR=/pnpm-store",
            "--env-file", "/dev/null",
        ]
        for mount in self.mounts:
            mode = "ro" if mount.read_only else "rw"
            argv.extend(["-v", f"{mount.source}:{mount.target}:{mode}"])
        pnpm_store = Path.home() / ".local/share/pnpm/store"
        if pnpm_store.exists():
            argv.extend(["-v", f"{pnpm_store}:/pnpm-store:rw"])
        argv.extend([self.image, "sh", "-c", command])
        proc = await asyncio.create_subprocess_exec(
            *argv,
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
            with contextlib.suppress(Exception):
                proc.kill()
            return SandboxCommandResult(stdout="", stderr="", exit_code=124, timed_out=True)

    def read_file(self, path: str, *, encoding: str = "utf-8") -> str:
        cid = self._assert_provisioned()
        result = subprocess.run(
            ["docker", "exec", cid, "cat", path],
            capture_output=True,
        )
        return result.stdout.decode(encoding, errors="replace")

    def write_file(self, path: str, content: str, *, encoding: str = "utf-8") -> None:
        cid = self._assert_provisioned()
        subprocess.run(
            ["docker", "exec", "-i", cid, "sh", "-c", f"mkdir -p $(dirname {path}) && cat > {path}"],
            input=content.encode(encoding),
            check=True,
        )

    def list_dir(self, path: str) -> list[Path]:
        cid = self._assert_provisioned()
        result = subprocess.run(
            ["docker", "exec", cid, "ls", "-1", path],
            capture_output=True,
        )
        names = result.stdout.decode(errors="replace").splitlines()
        return [Path(path) / name for name in names if name]


_active_sandbox: ContextVar[BaseSandbox | None] = ContextVar("active_sandbox", default=None)
_default_sandbox: BaseSandbox = LocalSandbox()


def get_default_sandbox() -> BaseSandbox:
    sandbox = _active_sandbox.get()
    return sandbox or _default_sandbox


def set_default_sandbox(sandbox: BaseSandbox) -> None:
    global _default_sandbox
    _default_sandbox = sandbox


@contextlib.contextmanager
def sandbox_context(sandbox: BaseSandbox):
    token = _active_sandbox.set(sandbox)
    try:
        yield sandbox
    finally:
        _active_sandbox.reset(token)


def get_sandbox_resources() -> dict[str, Any]:
    return {
        "memory": settings.sandbox_memory,
        "cpus": settings.sandbox_cpus,
    }


def create_session_sandbox(*, session_id: str, cwd: str | None = None) -> BaseSandbox:
    """Create the default sandbox for a managed session."""
    backend = settings.sandbox_backend.lower()
    if backend == "auto":
        backend = "docker" if shutil.which("docker") else "local"

    workspace = Path(cwd or Path.cwd()).resolve()
    if backend == "docker":
        return DockerSandbox(
            image=settings.sandbox_docker_image,
            work_dir=str(workspace),
            network=settings.sandbox_network,
            mounts=[
                SandboxMount(
                    source=str(workspace),
                    target=str(workspace),
                    read_only=False,
                )
            ],
        )
    if backend == "local":
        if settings.sandbox_require_isolation:
            raise RuntimeError(
                "sandbox_require_isolation=True but Docker is unavailable. "
                "Install Docker or set SANDBOX_REQUIRE_ISOLATION=false to allow "
                "LocalSandbox fallback."
            )
        return LocalSandbox(workspace_root=str(workspace))
    raise ValueError(f"Unsupported sandbox backend: {backend} (session {session_id})")
