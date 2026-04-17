"""Core agent loop — model-agnostic, harness-hooked, production-grade.

Lifecycle of a user message:
  1. PRE-PROCESSING
     - Register built-in tools (filesystem, shell, web)
     - Discover available skills
     - Register skill meta-tools (list_skills, load_skill, etc.)
     - Build system prompt with skill index (Level 1)

  2. AGENT LOOP
     a. Context management — fit messages within token budget
     b. Send to LLM via LiteLLM (messages + active tool schemas)
     c. Parse response:
        - Text only → done
        - Tool calls → validate → execute → append results
        - Malformed call → return error with retry hint
     d. If skill loaded/unloaded → rebuild system prompt in messages
     e. Check runtime limits (steps, timeout)
     f. Loop

  3. POST-PROCESSING
     - Finalize trace with metrics
     - Return trace
"""

from __future__ import annotations

import uuid
from typing import Callable

from agent.runtime.orchestrator import SessionOrchestrator
from agent.core.models import AgentEvent, EventType
from agent.session.engine import SessionEngine
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.trace import Trace


EventCallback = Callable[[AgentEvent], None]

# Skills that modify the tool registry — system prompt must be rebuilt after these
_SKILL_MUTATING_TOOLS = {"load_skill", "unload_skill"}


def _noop_callback(event: AgentEvent) -> None:
    pass


async def run_agent(
    user_input: str,
    model: str,
    context_strategy: str = "truncate",
    runtime_config: RuntimeConfig | None = None,
    event_callback: EventCallback | None = None,
) -> Trace:
    """Run the agent loop for a single user request."""
    callback = event_callback or _noop_callback
    config = runtime_config or RuntimeConfig()
    guard = RuntimeGuard(config)
    run_id = str(uuid.uuid4())[:8]

    # Initialize trace
    trace = Trace(
        run_id=run_id,
        model=model,
        scenario="general",
        prompt=user_input,
        context_strategy=context_strategy,
    )

    session = SessionEngine(model=model, context_strategy=context_strategy)

    # Emit start event
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
        orchestrator = SessionOrchestrator()
        handle = orchestrator.create_runtime(
            session_engine=session,
            model=model,
            runtime_config=config,
        )
        await handle.runtime.run_to_completion(user_input=user_input, trace=trace, callback=callback)
    except Exception as e:
        trace.finish(error=str(e))
        callback(AgentEvent(
            type=EventType.AGENT_ERROR,
            step=guard.step_count,
            data={"error": str(e)},
        ))

    return trace
