"""Built-in shell tool: run commands with safety guardrails."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent.runtime.sandbox import get_default_sandbox
from agent.core.models import ToolParameter, ToolGroup
from tools.base import BuiltinTool

# Commands that are blocked by default
BLOCKED_COMMANDS = {"rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"}


class RunCommandTool(BuiltinTool):
    name = "run_command"
    description = (
        "Run a shell command and return its output. "
        "Use for system operations, running scripts, git commands, etc. "
        "Commands run with a 30-second timeout by default."
    )
    parameters = [
        ToolParameter(name="command", type="string", description="Shell command to execute"),
        ToolParameter(
            name="timeout",
            type="integer",
            description="Timeout in seconds (default: 30, max: 120)",
            required=False,
            default=30,
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        command = kwargs["command"]
        timeout = min(kwargs.get("timeout", 30), 120)

        # Basic safety check
        cmd_lower = command.lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return f"Error: Command blocked for safety: {command}"

        try:
            before = _snapshot_result_files()
            result = await get_default_sandbox().run_command(command, timeout)
            if result.timed_out:
                return f"Error: Command timed out after {timeout}s: {command}"
            after = _snapshot_result_files()

            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(f"[stderr]\n{result.stderr}")

            output = "\n".join(output_parts).strip() or "(no output)"
            generated = _detect_changed_files(before, after)
            if generated:
                output += "\n\n[generated files]\n" + "\n".join(f"- {path}" for path in generated)
            return output + f"\n[exit code: {result.exit_code}]"
        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s: {command}"
        except Exception as e:
            return f"Error running command: {e}"
    tool_group = ToolGroup.RUNTIME
    requires_confirmation = True
    is_networked = True
    shell_command_arg = "command"


def _snapshot_result_files() -> dict[str, tuple[int, int]]:
    sandbox = get_default_sandbox()
    workspace_root = Path(getattr(sandbox, "workspace_root", Path.cwd()))
    roots = [workspace_root / "results", workspace_root / "charts"]

    snapshot: dict[str, tuple[int, int]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[str(path.relative_to(workspace_root))] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _detect_changed_files(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    changed: list[str] = []
    for path, meta in after.items():
        if before.get(path) != meta:
            changed.append(path)
    return sorted(changed)
