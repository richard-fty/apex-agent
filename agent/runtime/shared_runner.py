"""Shared event-driven runner for CLI and TUI REPL flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from agent.runtime.orchestrator import SessionOrchestrator
from agent.runtime.guards import RuntimeConfig


@dataclass
class RunnerEvent:
    """A UI-friendly runtime event emitted during a turn."""

    type: str
    data: dict[str, Any]


class SharedTurnRunner:
    """Run one turn as an event stream, including pause/resume for approvals."""

    def __init__(
        self,
        session_engine: Any,
        access_controller: Any,
        cost_tracker: Any,
        model: str,
        runtime_config: RuntimeConfig,
    ) -> None:
        orchestrator = SessionOrchestrator()
        self.runtime = orchestrator.create_runtime(
            session_engine=session_engine,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
            model=model,
            runtime_config=runtime_config,
        ).runtime

    async def start_turn(self, user_input: str) -> AsyncIterator[RunnerEvent]:
        async for event in self.runtime.start_turn(user_input):
            yield RunnerEvent(event.type, event.data)

    async def resume_pending(self, action: str) -> AsyncIterator[RunnerEvent]:
        async for event in self.runtime.resume_pending(action):
            yield RunnerEvent(event.type, event.data)
