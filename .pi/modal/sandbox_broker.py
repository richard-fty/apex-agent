from __future__ import annotations

import json
import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import modal


BROKER_HOST = "127.0.0.1"
BROKER_PORT = int(os.getenv("APEX_SANDBOX_BROKER_PORT", "8790"))
WORKSPACE = os.getenv("APEX_REMOTE_WORKSPACE", "/workspace")
APP_NAME = os.getenv("APEX_SANDBOX_APP_NAME", "apex-sandbox")
VOLUME_NAME = os.getenv("APEX_WORKSPACE_VOLUME", "apex-workspace")


class SandboxManager:
    def __init__(self) -> None:
        token_id = os.environ["APEX_MODAL_TOKEN_ID"]
        token_secret = os.environ["APEX_MODAL_TOKEN_SECRET"]
        self.client = modal.Client.from_credentials(token_id, token_secret)
        self.app = modal.App.lookup(
            APP_NAME,
            create_if_missing=True,
            client=self.client,
        )
        self.volume = modal.Volume.from_name(
            VOLUME_NAME,
            create_if_missing=True,
            client=self.client,
        )
        self.image = (
            modal.Image.from_registry("node:24-bookworm-slim", add_python="3.13")
            .apt_install("bash", "ca-certificates", "curl", "ffmpeg", "git", "ripgrep")
            .run_commands(f"mkdir -p {WORKSPACE}")
        )
        self._sandbox: Any | None = None
        self._lock = threading.RLock()

    @property
    def sandbox_id(self) -> str | None:
        sandbox = self._sandbox
        return sandbox.object_id if sandbox is not None else None

    def ensure(self) -> Any:
        with self._lock:
            if self._sandbox is not None:
                return self._sandbox
            self._sandbox = modal.Sandbox.create(
                app=self.app,
                image=self.image,
                workdir=WORKSPACE,
                volumes={WORKSPACE: self.volume},
                timeout=int(os.getenv("APEX_SANDBOX_TIMEOUT_SECONDS", "600")),
                idle_timeout=int(os.getenv("APEX_SANDBOX_IDLE_TIMEOUT_SECONDS", "180")),
                cpu=(
                    float(os.getenv("APEX_SANDBOX_CPU", "0.5")),
                    float(os.getenv("APEX_SANDBOX_CPU_LIMIT", "1.0")),
                ),
                memory=(
                    int(os.getenv("APEX_SANDBOX_MEMORY_MB", "512")),
                    int(os.getenv("APEX_SANDBOX_MEMORY_LIMIT_MB", "1024")),
                ),
                client=self.client,
            )
            return self._sandbox

    def exec(
        self,
        *,
        command: str,
        cwd: str,
        timeout: int,
        env: dict[str, str],
    ) -> dict[str, Any]:
        if len(command) > 50_000:
            raise ValueError("Command exceeds 50,000 characters")
        if not cwd.startswith(WORKSPACE):
            raise ValueError(f"cwd must stay inside {WORKSPACE}")
        timeout = max(1, min(timeout, 600))
        sandbox = self.ensure()
        try:
            self.volume.commit()
        except Exception:
            pass
        try:
            sandbox.reload_volumes()
        except Exception:
            pass
        shell_env = " ".join(
            f"{key}={json.dumps(value)}"
            for key, value in env.items()
            if key.replace("_", "").isalnum()
        )
        shell_command = f"cd {json.dumps(cwd)} && "
        if shell_env:
            shell_command += f"env {shell_env} "
        shell_command += command
        process = sandbox.exec("bash", "-lc", shell_command, timeout=timeout)
        with ThreadPoolExecutor(max_workers=2) as executor:
            stdout_future = executor.submit(process.stdout.read)
            stderr_future = executor.submit(process.stderr.read)
            process.wait()
            stdout = stdout_future.result()
            stderr = stderr_future.result()
        try:
            sync_process = sandbox.exec("sync", WORKSPACE, timeout=30)
            sync_process.wait()
            self.volume.reload()
        except Exception:
            pass
        return {
            "ok": True,
            "sandbox_id": sandbox.object_id,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode,
        }

    def destroy(self) -> None:
        with self._lock:
            sandbox = self._sandbox
            self._sandbox = None
        if sandbox is None:
            return
        try:
            sandbox.terminate()
        finally:
            sandbox.detach()


manager = SandboxManager()


class BrokerHandler(BaseHTTPRequestHandler):
    server_version = "ApexModalSandboxBroker/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[sandbox-broker] {format % args}", flush=True)

    def send_json(self, status: int, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length > 1_000_000:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length)
        value = json.loads(raw or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "backend": "modal",
                    "sandbox_id": manager.sandbox_id,
                },
            )
            return
        self.send_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        try:
            body = self.read_json()
            if self.path == "/v1/sandbox/exec":
                command = body.get("command")
                if not isinstance(command, str) or not command.strip():
                    raise ValueError("command is required")
                cwd = body.get("cwd", WORKSPACE)
                env = body.get("env", {})
                if not isinstance(cwd, str) or not isinstance(env, dict):
                    raise ValueError("Invalid cwd or env")
                clean_env = {
                    str(key): str(value)
                    for key, value in env.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
                result = manager.exec(
                    command=command,
                    cwd=cwd,
                    timeout=int(body.get("timeout", 120)),
                    env=clean_env,
                )
                self.send_json(200, result)
                return
            if self.path == "/v1/sandbox/destroy":
                manager.destroy()
                self.send_json(200, {"ok": True})
                return
            self.send_json(404, {"ok": False, "error": "Not found"})
        except ValueError as error:
            self.send_json(400, {"ok": False, "error": str(error)})
        except Exception as error:
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                    "sandbox_id": manager.sandbox_id,
                },
            )


def shutdown(*_: object) -> None:
    manager.destroy()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

server = ThreadingHTTPServer((BROKER_HOST, BROKER_PORT), BrokerHandler)
print(f"Apex Modal Sandbox broker listening on {BROKER_HOST}:{BROKER_PORT}", flush=True)
server.serve_forever()
