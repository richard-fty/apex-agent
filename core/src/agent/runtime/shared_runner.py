"""Shared event-driven runner for CLI, TUI, and FastAPI server flows.

SharedTurnRunner kicks off a turn (or resume) as a background task and
exposes a per-turn `RunnerEvent` stream to the UI. The stream is backed by
the runtime's `EventBus` — no archive polling, no stop-state inference.
A subscription ends when the runtime emits `StreamEnd`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

from agent.core.models import TokenUsage
from agent.events import (
    ApprovalRequested,
    AssistantMessage,
    AssistantNote,
    AssistantToken,
    ErrorEvent,
    EventBus,
    InMemoryEventBus,
    PlanUpdated,
    SkillAutoLoaded,
    StreamEnd,
    ToolDenied,
    ToolFinished,
    ToolStarted,
    TurnFinished,
    TurnStarted,
    UsageEvent,
)
from agent.events.schema import AgentEvent as TypedAgentEvent
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.loop import create_session
from agent.runtime.sandbox import BaseSandbox
from agent.session.archive import SessionArchive


@dataclass
class RunnerEvent:
    """A UI-friendly runtime event emitted during a turn."""

    type: str
    data: dict[str, Any]


def _translate(event: TypedAgentEvent) -> RunnerEvent | None:
    """Map a typed AgentEvent to the UI's RunnerEvent shape.

    Returns None for events that aren't user-visible (e.g., StreamEnd is
    handled by the stream, not surfaced to the UI caller).
    """
    if isinstance(event, AssistantToken):
        return RunnerEvent("token", {"text": event.text})
    if isinstance(event, AssistantNote):
        return RunnerEvent("assistant_note", {"text": event.text})
    if isinstance(event, AssistantMessage):
        return RunnerEvent("assistant_message", {"content": event.content})
    if isinstance(event, ToolStarted):
        return RunnerEvent(
            "tool_started",
            {"name": event.name, "arguments": event.arguments, "step": event.step},
        )
    if isinstance(event, ToolFinished):
        return RunnerEvent(
            "tool_finished",
            {
                "name": event.name,
                "arguments": event.arguments,
                "success": event.success,
                "duration_ms": event.duration_ms,
                "content": event.content,
            },
        )
    if isinstance(event, ToolDenied):
        return RunnerEvent("tool_denied", {"name": event.name, "reason": event.reason})
    if isinstance(event, ApprovalRequested):
        return RunnerEvent(
            "approval_requested",
            {"tool_name": event.tool_name, "reason": event.reason, "step": event.step},
        )
    if isinstance(event, TurnStarted):
        return RunnerEvent("turn_started", {"user_input": event.user_input})
    if isinstance(event, TurnFinished):
        return RunnerEvent("turn_finished", {"content": event.content})
    if isinstance(event, ErrorEvent):
        return RunnerEvent("error", {"message": event.message})
    if isinstance(event, UsageEvent):
        return RunnerEvent(
            "usage",
            {"step": event.step, "usage": event.usage, "duration_ms": event.duration_ms},
        )
    if isinstance(event, SkillAutoLoaded):
        return RunnerEvent("skill_auto_loaded", {"skill_name": event.skill_name})
    if isinstance(event, PlanUpdated):
        return RunnerEvent(
            "plan_updated",
            {"steps": [s.model_dump() for s in event.steps]},
        )
    return None


class SessionEventStream:
    """Translate a bus subscription into a RunnerEvent stream.

    Kept as a public class so the FastAPI SSE handler and the TUI can use
    the same translator. For SSE the raw typed events are what get sent on
    the wire; this class is for in-process clients (TUI, CLI).
    """

    def __init__(self, bus: EventBus, session_id: str) -> None:
        self.bus = bus
        self.session_id = session_id

    async def stream(
        self, *, since_seq: int | None = None
    ) -> AsyncIterator[RunnerEvent]:
        async for event in self.bus.subscribe(self.session_id, since_seq=since_seq):
            # StreamEnd closes the bus iterator for us; still translate+skip.
            translated = _translate(event)
            if translated is not None:
                yield translated


class SharedTurnRunner:
    """Run one turn and expose its event stream to UI consumers."""

    def __init__(
        self,
        session_engine: Any,
        access_controller: Any,
        cost_tracker: Any,
        model: str,
        runtime_config: RuntimeConfig,
        archive: SessionArchive | None = None,
        sandbox: BaseSandbox | None = None,
        event_bus: EventBus | None = None,
        session_id: str | None = None,
    ) -> None:
        self._archive = archive or SessionArchive()
        self._event_bus: EventBus = event_bus or InMemoryEventBus()
        orchestrator, handle = create_session(
            session_engine=session_engine,
            model=model,
            runtime_config=runtime_config,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
            sandbox=sandbox,
            archive=self._archive,
            event_bus=self._event_bus,
            session_id=session_id,
        )
        self.runtime = handle.runtime
        self._orchestrator = orchestrator
        self._handle = handle
        self._active_task: asyncio.Task[None] | None = None

    # ---- properties --------------------------------------------------------

    @property
    def access_controller(self) -> Any:
        return self.runtime.access_controller

    @access_controller.setter
    def access_controller(self, controller: Any) -> None:
        self.runtime.access_controller = controller

    @property
    def session_id(self) -> str:
        return self._handle.session_id

    @property
    def archive(self) -> SessionArchive:
        return self._archive

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    # ---- background execution --------------------------------------------

    async def _run_turn_task(self, user_input: str) -> None:
        guard = RuntimeGuard(self.runtime.runtime_config)
        try:
            async for _ in self.runtime.start_turn(user_input, guard=guard):
                pass
        except Exception as exc:
            # Make sure subscribers don't hang on an unhandled task exception.
            await self._event_bus.publish(
                self.session_id,
                ErrorEvent(session_id=self.session_id, message=str(exc)),
            )
            await self._event_bus.publish(
                self.session_id,
                StreamEnd(
                    session_id=self.session_id, final_state="failed", reason=str(exc),
                ),
            )
            raise

    async def _resume_turn_task(self, action: str) -> None:
        guard = RuntimeGuard(self.runtime.runtime_config)
        try:
            async for _ in self.runtime.resume_pending(action, guard=guard):
                pass
        except Exception as exc:
            await self._event_bus.publish(
                self.session_id,
                ErrorEvent(session_id=self.session_id, message=str(exc)),
            )
            await self._event_bus.publish(
                self.session_id,
                StreamEnd(
                    session_id=self.session_id, final_state="failed", reason=str(exc),
                ),
            )
            raise

    def start_turn_background(self, user_input: str) -> None:
        """Kick off a turn without blocking; callers subscribe to the bus."""
        self._active_task = asyncio.create_task(self._run_turn_task(user_input))

    def resume_pending_background(self, action: str) -> None:
        self._active_task = asyncio.create_task(self._resume_turn_task(action))

    # ---- foreground stream API (TUI/CLI) ---------------------------------

    async def start_turn(self, user_input: str) -> AsyncIterator[RunnerEvent]:
        self.start_turn_background(user_input)
        try:
            async for event in SessionEventStream(self._event_bus, self.session_id).stream():
                yield event
            if self._active_task is not None:
                await self._active_task
        except Exception as exc:
            if self._active_task is not None:
                self._active_task.cancel()
            yield RunnerEvent("error", {"message": str(exc)})
        finally:
            self._active_task = None

    async def resume_pending(self, action: str) -> AsyncIterator[RunnerEvent]:
        self.resume_pending_background(action)
        try:
            async for event in SessionEventStream(self._event_bus, self.session_id).stream():
                yield event
            if self._active_task is not None:
                await self._active_task
        except Exception as exc:
            if self._active_task is not None:
                self._active_task.cancel()
            yield RunnerEvent("error", {"message": str(exc)})
        finally:
            self._active_task = None
