"""Core agent loop and harness entry points.

All execution paths funnel through SessionOrchestrator so limit enforcement,
session persistence, and archive wiring are handled in one place (Gap 9).

Public API
----------
run_agent()        One-shot request → Trace (used by eval runner).
create_session()   Build a (orchestrator, handle) pair for REPL flows;
                   replaces the separate SharedTurnRunner + orchestrator wiring
                   that was previously spread across shared_runner.py and callers.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from agent.runtime.orchestrator import SessionOrchestrator, SessionHandle
from agent.core.models import AgentEvent, EventType
from agent.session.engine import SessionEngine
from agent.session.archive import SessionArchive
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.sandbox import BaseSandbox
from agent.runtime.trace import Trace


EventCallback = Callable[[AgentEvent], None]


def _noop_callback(event: AgentEvent) -> None:
    pass


async def run_agent(
    user_input: str,
    model: str,
    context_strategy: str = "truncate",
    runtime_config: RuntimeConfig | None = None,
    event_callback: EventCallback | None = None,
) -> Trace:
    """Run the agent loop for a single user request and return its Trace."""
    callback = event_callback or _noop_callback
    config = runtime_config or RuntimeConfig()
    run_id = str(uuid.uuid4())[:8]

    trace = Trace(
        run_id=run_id,
        model=model,
        scenario="general",
        prompt=user_input,
        context_strategy=context_strategy,
    )

    session = SessionEngine(model=model, context_strategy=context_strategy)
    callback(AgentEvent(
        type=EventType.AGENT_START,
        data={
            "run_id": run_id,
            "model": model,
            "available_skills": session.skill_loader.get_available_skill_names(),
            "available_tools": session.dispatch.tool_names,
        },
    ))

    try:
        archive = SessionArchive()
        orchestrator = SessionOrchestrator(archive=archive)
        handle = orchestrator.create_runtime(
            session_engine=session,
            model=model,
            runtime_config=config,
        )
        guard = RuntimeGuard(config)
        await handle.runtime.run_to_completion(
            user_input=user_input, guard=guard, trace=trace, callback=callback
        )
    except Exception as exc:
        trace.finish(error=str(exc))
        callback(AgentEvent(type=EventType.AGENT_ERROR, data={"error": str(exc)}))

    return trace


def create_session(
    *,
    session_engine: Any,
    model: str,
    runtime_config: RuntimeConfig | None = None,
    access_controller: Any | None = None,
    cost_tracker: Any | None = None,
    archive: SessionArchive | None = None,
    sandbox: BaseSandbox | None = None,
    event_bus: Any | None = None,
    session_id: str | None = None,
) -> tuple[SessionOrchestrator, SessionHandle]:
    """Build a (orchestrator, handle) pair for REPL / TUI flows.

    Callers should drive turns via ``orchestrator.run_turn(handle, user_input)``
    so the guard is created externally rather than inside the harness.
    """
    config = runtime_config or RuntimeConfig()
    arc = archive or SessionArchive()
    orchestrator = SessionOrchestrator(archive=arc)
    handle = orchestrator.create_runtime(
        session_engine=session_engine,
        model=model,
        runtime_config=config,
        access_controller=access_controller,
        cost_tracker=cost_tracker,
        sandbox=sandbox,
        event_bus=event_bus,
        session_id=session_id,
    )
    return orchestrator, handle
