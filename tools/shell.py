"""Built-in shell tool: run commands with safety guardrails."""

from __future__ import annotations

import asyncio
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
            result = await get_default_sandbox().run_command(command, timeout)
            if result.timed_out:
                return f"Error: Command timed out after {timeout}s: {command}"

            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(f"[stderr]\n{result.stderr}")

            output = "\n".join(output_parts).strip() or "(no output)"
            return output + f"\n[exit code: {result.exit_code}]"
        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s: {command}"
        except Exception as e:
            return f"Error running command: {e}"
    tool_group = ToolGroup.RUNTIME
    requires_confirmation = True
    is_networked = True
    shell_command_arg = "command"
