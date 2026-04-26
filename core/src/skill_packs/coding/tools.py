"""Tools for the coding skill pack."""

from __future__ import annotations

import json
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from agent.artifacts import ArtifactKind, ArtifactSpec
from agent.core.models import ToolDef, ToolGroup, ToolParameter
from agent.events import PlanStep, PlanUpdated
from agent.runtime.sandbox import get_default_sandbox
from agent.runtime.tool_context import (
    emit_artifact_append,
    emit_artifact_created,
    emit_artifact_finalized,
    get_tool_context,
)


def get_tools() -> list[tuple[ToolDef, Any]]:
    return [
        (
            ToolDef(
                name="apply_patch",
                description="Apply a unified diff patch to the current workspace.",
                parameters=[
                    ToolParameter(name="patch", type="string", description="Unified diff patch text"),
                ],
                requires_confirmation=True,
                tool_group=ToolGroup.SKILL,
            ),
            apply_patch,
        ),
        (
            ToolDef(
                name="update_plan",
                description="Replace the visible TodoItem checklist for the current task.",
                parameters=[
                    ToolParameter(
                        name="steps",
                        type="string",
                        description='JSON array of TodoItems: [{"id":"t1","text":"...","status":"pending"}]',
                    ),
                ],
                requires_confirmation=False,
                mutates_state=False,
                tool_group=ToolGroup.ADMIN,
            ),
            update_plan,
        ),
        (
            ToolDef(
                name="start_app_preview",
                description=(
                    "Start the generated frontend app on localhost and create an app_preview "
                    "artifact so the user can inspect it in the side panel."
                ),
                parameters=[
                    ToolParameter(
                        name="command",
                        type="string",
                        description=(
                            "Command used to start the app. Use {port} as a placeholder. "
                            "If omitted, the tool auto-detects Vite, Next.js, or static HTML."
                        ),
                        required=False,
                    ),
                    ToolParameter(
                        name="port",
                        type="integer",
                        description="Preferred localhost port. If unavailable, a free port is selected.",
                        required=False,
                    ),
                    ToolParameter(
                        name="cwd",
                        type="string",
                        description="Directory containing the app, relative to the workspace.",
                        required=False,
                        default=".",
                    ),
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Artifact display name.",
                        required=False,
                        default="App preview",
                    ),
                ],
                requires_confirmation=True,
                tool_group=ToolGroup.SKILL,
                shell_command_arg="command",
            ),
            start_app_preview,
        ),
    ]


async def apply_patch(patch: str) -> str:
    patch_path = ".apex_patch.diff"
    sandbox = get_default_sandbox()
    sandbox.write_file(str(Path(patch_path).resolve()), patch)
    result = await sandbox.run_command(f"git apply --whitespace=nowarn {patch_path}", timeout=30)
    if result.exit_code != 0:
        return f"Patch failed:\n{result.stderr or result.stdout}"

    artifact_id = await emit_artifact_created(
        spec=ArtifactSpec(
            kind=ArtifactKind.CODE,
            name="patch.diff",
            language="diff",
            description="Applied patch",
        )
    )
    if artifact_id:
        await emit_artifact_append(artifact_id, patch)
        await emit_artifact_finalized(artifact_id)
    return "Patch applied."


async def update_plan(steps: str) -> str:
    try:
        raw_steps = json.loads(steps)
    except json.JSONDecodeError as exc:
        return f"Error: invalid TodoItem JSON: {exc}"
    if not isinstance(raw_steps, list):
        return "Error: steps must be a JSON array."

    todo_items = []
    for index, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            continue
        status = _normalize_status(item.get("status", "pending"))
        todo_items.append(
            PlanStep(
                id=str(item.get("id", index)),
                text=str(item.get("text", item.get("title", ""))),
                status=status,
            )
        )

    ctx = get_tool_context()
    if ctx is not None:
        await ctx.event_bus.publish(
            ctx.session_id,
            PlanUpdated(session_id=ctx.session_id, turn_id=ctx.turn_id, steps=todo_items),
        )
    return f"Todo checklist updated: {len(todo_items)} items."


async def start_app_preview(
    command: str | None = None,
    port: int | None = None,
    cwd: str = ".",
    name: str = "App preview",
) -> str:
    sandbox = get_default_sandbox()
    workspace = Path(getattr(sandbox, "workspace_root", Path.cwd())).resolve()
    app_dir = (workspace / cwd).resolve()
    if not _is_relative_to(app_dir, workspace):
        return f"Error: preview cwd must stay inside workspace: {cwd}"
    if not app_dir.exists() or not app_dir.is_dir():
        return f"Error: preview cwd does not exist: {cwd}"

    selected_port = _select_port(port)
    preview_command = command or _detect_preview_command(app_dir)
    if not preview_command:
        return (
            "Error: could not infer how to start this app. Provide a command, "
            "for example: pnpm dev --host 127.0.0.1 --port {port}"
        )
    preview_command = preview_command.replace("{port}", str(selected_port))

    log_path = app_dir / ".apex_preview.log"
    pid_path = app_dir / ".apex_preview.pid"
    await _stop_previous_preview(sandbox, pid_path)
    shell = (
        f"cd {shlex.quote(str(app_dir))} && "
        f"nohup sh -c {shlex.quote(preview_command)} "
        f"> {shlex.quote(str(log_path))} 2>&1 < /dev/null & "
        f"echo $! > {shlex.quote(str(pid_path))}"
    )
    result = await sandbox.run_command(shell, timeout=10)
    if result.exit_code != 0:
        return f"Error: failed to start preview command:\n{result.stderr or result.stdout}"

    url = f"http://127.0.0.1:{selected_port}"
    ready, last_error = _wait_for_url(url, timeout_sec=25)
    if not ready:
        log = _read_text(log_path, limit=4000)
        return (
            f"Error: preview server did not become ready at {url}.\n"
            f"Last check: {last_error}\n"
            f"Command: {preview_command}\n"
            f"Log:\n{log}"
        )

    artifact_id = await emit_artifact_created(
        spec=ArtifactSpec(
            kind=ArtifactKind.APP_PREVIEW,
            name=name or "App preview",
            description=f"Live app preview at {url}",
        )
    )
    if artifact_id:
        await emit_artifact_replace(artifact_id, url)
        await emit_artifact_finalized(artifact_id)

    return (
        f"App preview started: {url}\n"
        f"Command: {preview_command}\n"
        f"PID file: {pid_path.relative_to(workspace)}"
    )


def _normalize_status(value: Any) -> str:
    raw = str(value or "pending")
    if raw in {"pending", "in_progress", "completed", "failed"}:
        return raw
    if raw == "done":
        return "completed"
    if raw == "blocked":
        return "pending"
    if raw in {"cancelled", "skipped"}:
        return "failed"
    return "pending"


async def _stop_previous_preview(sandbox: Any, pid_path: Path) -> None:
    if not pid_path.exists():
        return
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if pid <= 0:
        return
    await sandbox.run_command(f"kill {pid} >/dev/null 2>&1 || true", timeout=5)


def _detect_preview_command(app_dir: Path) -> str | None:
    package_json = app_dir / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts") if isinstance(package, dict) else {}
        deps = {
            **(package.get("dependencies", {}) if isinstance(package, dict) else {}),
            **(package.get("devDependencies", {}) if isinstance(package, dict) else {}),
        }
        runner = _detect_package_runner(app_dir, package if isinstance(package, dict) else {})
        if isinstance(scripts, dict) and "dev" in scripts:
            if "next" in deps:
                return f"{runner} dev -H 127.0.0.1 -p {{port}}"
            return f"{runner} dev --host 127.0.0.1 --port {{port}}"
        if isinstance(scripts, dict) and "start" in scripts:
            return f"{runner} start -- --host 127.0.0.1 --port {{port}}"
    if (app_dir / "index.html").exists():
        return "python3 -m http.server {port} --bind 127.0.0.1"
    return None


def _detect_package_runner(app_dir: Path, package: dict[str, Any]) -> str:
    manager = str(package.get("packageManager", ""))
    if manager.startswith("pnpm") or (app_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if manager.startswith("yarn") or (app_dir / "yarn.lock").exists():
        return "yarn"
    if (app_dir / "package-lock.json").exists():
        return "npm run"
    return "pnpm"


def _select_port(preferred: int | None) -> int:
    if preferred and _port_available(preferred):
        return preferred
    for candidate in range(6173, 6273):
        if _port_available(candidate):
            return candidate
    raise RuntimeError("No available localhost preview port found in range 6173-6272")


def _port_available(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_url(url: str, *, timeout_sec: int) -> tuple[bool, str]:
    deadline = time.time() + timeout_sec
    last_error = "not checked"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 500:
                    return True, ""
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    return False, last_error


def _read_text(path: Path, *, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"(could not read {path}: {exc})"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
