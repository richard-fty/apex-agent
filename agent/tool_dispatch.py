"""Tool dispatch — registration, schema generation, validation, execution, and retry.

This replaces what PydanticAI/LangChain would do, in ~100 lines we fully control.
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Callable, Awaitable

from agent.models import ToolCall, ToolDef, ToolGroup, ToolLoadingStrategy, ToolResult


# Type for tool handler functions
ToolHandler = Callable[..., Awaitable[str] | str]


class ToolDispatch:
    """Registry and dispatcher for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, tool_def: ToolDef, handler: ToolHandler) -> None:
        """Register a tool with its definition and handler function."""
        self._tools[tool_def.name] = tool_def
        self._handlers[tool_def.name] = handler

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)
        self._handlers.pop(name, None)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool_def(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_tool_defs(
        self,
        *,
        include_runtime_injected: bool = False,
        groups: set[ToolGroup] | None = None,
    ) -> list[ToolDef]:
        tools = list(self._tools.values())
        filtered = [
            td for td in tools
            if (td.visible or (
                include_runtime_injected
                and td.loading_strategy == ToolLoadingStrategy.RUNTIME_INJECTED
            ))
            and (groups is None or td.tool_group in groups)
            and (
                include_runtime_injected
                or td.loading_strategy != ToolLoadingStrategy.RUNTIME_INJECTED
            )
        ]
        order = {
            ToolGroup.CORE: 0,
            ToolGroup.SKILL: 1,
            ToolGroup.RETRIEVAL: 2,
            ToolGroup.RUNTIME: 3,
            ToolGroup.ADMIN: 4,
        }
        return sorted(filtered, key=lambda td: (order.get(td.tool_group, 99), td.name))

    def to_openai_tools(
        self,
        *,
        include_runtime_injected: bool = False,
        groups: set[ToolGroup] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate OpenAI-format tool schemas for LLM request."""
        return [
            td.to_openai_schema()
            for td in self.list_tool_defs(
                include_runtime_injected=include_runtime_injected,
                groups=groups,
            )
        ]

    def parse_tool_calls(self, raw_tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse raw tool calls from LLM response into ToolCall objects."""
        parsed = []
        for raw in raw_tool_calls:
            func = raw.get("function", {})
            name = func.get("name", "")
            args_str = func.get("arguments", "{}")

            try:
                arguments = json.loads(args_str)
            except json.JSONDecodeError:
                arguments = {"_raw": args_str, "_parse_error": True}

            parsed.append(ToolCall(
                id=raw.get("id", ""),
                name=name,
                arguments=arguments,
            ))
        return parsed

    def validate_call(self, tool_call: ToolCall) -> str | None:
        """Validate a tool call against its schema.

        Returns None if valid, or an error message string.
        """
        if tool_call.name not in self._tools:
            return f"Unknown tool: {tool_call.name}. Available: {', '.join(self.tool_names)}"

        if tool_call.arguments.get("_parse_error"):
            return f"Failed to parse arguments as JSON: {tool_call.arguments.get('_raw', '')}"

        tool_def = self._tools[tool_call.name]
        required_params = [p.name for p in tool_def.parameters if p.required]
        missing = [p for p in required_params if p not in tool_call.arguments]
        if missing:
            return f"Missing required parameters for {tool_call.name}: {', '.join(missing)}"

        return None

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call and return the result."""
        # Validate first
        error = self.validate_call(tool_call)
        if error:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=error,
                success=False,
                error=error,
                summary=error,
            )

        handler = self._handlers[tool_call.name]
        try:
            result = handler(**tool_call.arguments)
            # Support both sync and async handlers
            if hasattr(result, "__await__"):
                result = await result
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=str(result),
                success=True,
                summary=str(result)[:240],
            )
        except Exception as e:
            tb = traceback.format_exc()
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error executing {tool_call.name}: {e}",
                success=False,
                error=f"{e}\n{tb}",
                summary=f"Error executing {tool_call.name}: {e}",
            )

    def retry_prompt(self, tool_call: ToolCall, error: str) -> str:
        """Generate a retry hint message for the LLM after a failed tool call."""
        tool_def = self._tools.get(tool_call.name)
        if tool_def:
            params_desc = ", ".join(
                f"{p.name}: {p.type} ({'required' if p.required else 'optional'})"
                for p in tool_def.parameters
            )
            return (
                f"Tool call to '{tool_call.name}' failed: {error}\n"
                f"Expected parameters: {params_desc}\n"
                f"Please fix the arguments and try again."
            )
        return f"Tool call failed: {error}. Please try again with corrected arguments."
