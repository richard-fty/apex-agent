"""Execute validated tool calls and normalize tool results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.models import ToolCall


@dataclass
class ExecutedToolCall:
    """Normalized output from a tool execution."""

    tool_call: ToolCall
    success: bool
    content: str
    summary: str | None = None


class ToolExecutor:
    """Own tool validation, execution, and result compaction."""

    def __init__(self, dispatch: Any, context_manager: Any) -> None:
        self.dispatch = dispatch
        self.context_manager = context_manager

    async def execute(self, tool_call: ToolCall) -> ExecutedToolCall:
        validation_error = self.dispatch.validate_call(tool_call)
        if validation_error:
            content = self.dispatch.retry_prompt(tool_call, validation_error)
            return ExecutedToolCall(tool_call=tool_call, success=False, content=content)

        result = await self.dispatch.execute(tool_call)
        content = self.context_manager.compact_tool_result(result.content)
        return ExecutedToolCall(
            tool_call=tool_call,
            success=result.success,
            content=content,
            summary=result.summary,
        )
