"""Compatibility wrapper around the newer turn orchestrator."""

from __future__ import annotations

from typing import Any, Callable

from agent.models import AgentEvent
from agent.tool_executor import ToolExecutor
from agent.turn_orchestrator import TurnOrchestrator
from harness.runtime import RuntimeGuard
from harness.trace import Trace


EventCallback = Callable[[AgentEvent], None]


class TurnExecutor:
    """Backwards-compatible entry point for turn execution."""

    def __init__(self, session_engine: Any, callback: EventCallback) -> None:
        self.session = session_engine
        self.callback = callback
        self.tool_executor = ToolExecutor(session_engine.dispatch, session_engine.context_mgr)
        self.orchestrator = TurnOrchestrator(session_engine, callback, self.tool_executor)

    async def execute(self, user_input: str, guard: RuntimeGuard, trace: Trace) -> str:
        return await self.orchestrator.execute(user_input, guard, trace)
