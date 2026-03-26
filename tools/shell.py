"""Built-in shell tool: run commands with safety guardrails."""

from __future__ import annotations

import asyncio
from typing import Any

from agent.models import ToolParameter
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
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                output_parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace')}")

            output = "\n".join(output_parts).strip()
            if not output:
                output = "(no output)"

            exit_info = f"\n[exit code: {proc.returncode}]"
            return output + exit_info

        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s: {command}"
        except Exception as e:
            return f"Error running command: {e}"
