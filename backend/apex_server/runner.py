"""Runner lifecycle — build and cache SharedTurnRunner instances per session.

This module is the only place the server layer constructs runtimes. Keeping it
separate from route models and ownership helpers makes the import graph cleaner
and makes it possible to swap the runner model later (e.g. to an Arq worker)
without touching route definitions.
"""

from __future__ import annotations

import os

from agent.policy.access_control import AccessController
from agent.policy.policy_models import get_policy
from agent.runtime.guards import RuntimeConfig
from agent.runtime.shared_runner import SharedTurnRunner
from agent.session.engine import SessionEngine

from apex_server.deps import AppState


def get_or_build_runner(state: AppState, session_id: str, model: str) -> SharedTurnRunner:
    """Return the live session runner, creating it lazily for MVP mode."""
    runner = state.runners.get(session_id)
    if runner is not None:
        return runner

    engine = SessionEngine(model=model, context_strategy="truncate")
    policy_name = os.environ.get("APEX_POLICY", "auto")
    access = AccessController(policy=get_policy(policy_name))
    runner = SharedTurnRunner(
        session_engine=engine,
        access_controller=access,
        cost_tracker=None,
        model=model,
        runtime_config=RuntimeConfig(),
        archive=state.archive,
        event_bus=state.event_bus,
        session_id=session_id,
    )
    runner.runtime.artifact_store = state.artifact_store
    state.runners[session_id] = runner
    state.runtimes[session_id] = runner.runtime
    return runner