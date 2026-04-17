"""Wake — rebuild a ManagedAgentRuntime from the session archive.

Implements the article's `wake(session_id)` contract: a fresh stateless
harness can resume any session by replaying its event log.

Usage:
    archive = SessionArchive("results/sessions/archive.db")
    runtime = wake(archive, "session-abc-123", model="deepseek-chat", ...)
    async for event in runtime._run_loop():
        ...
"""

from __future__ import annotations

import logging
from typing import Any

from agent.core.models import AgentState, PendingApproval
from agent.runtime.guards import RuntimeConfig
from agent.runtime.managed_runtime import (
    LiteLLMBrain,
    ManagedAgentRuntime,
    SessionRecord,
)
from agent.session.archive import SessionArchive
from agent.session.engine import SessionEngine
from agent.session.store import SessionStore

logger = logging.getLogger(__name__)


def wake(
    archive: SessionArchive,
    session_id: str,
    *,
    runtime_config: RuntimeConfig | None = None,
    access_controller: Any | None = None,
    cost_tracker: Any | None = None,
) -> ManagedAgentRuntime:
    """Rebuild a ManagedAgentRuntime from a session's event log.

    This is the article's `wake(sessionId)` — a fresh harness boots on an
    existing session's durable log without losing any state.
    """
    session_meta = archive.load_session(session_id)
    if session_meta is None:
        raise ValueError(f"No session found: {session_id}")

    model = session_meta["model"]
    context_strategy = session_meta["context_strategy"]
    events = archive.get_events(session_id)

    logger.info("Waking session %s: %d events, model=%s", session_id, len(events), model)

    # 1. Rebuild SessionEngine with tools registered
    engine = SessionEngine(
        model=model,
        context_strategy=context_strategy,
        archive=archive,
        session_id=session_id,
    )

    # 2. Replay messages from events
    user_input = None
    for ev in events:
        etype = ev["type"]
        payload = ev["payload"]

        if etype == "user_message_added":
            msg = payload.get("message", payload)
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            engine.messages.append({"role": "user", "content": content})
        elif etype == "user_input_received":
            user_input = payload.get("user_input", "")
        elif etype == "assistant_message_added":
            msg = payload.get("message", payload)
            if isinstance(msg, dict):
                engine.messages.append(msg)
        elif etype == "tool_message_added":
            msg = payload.get("message", payload)
            if isinstance(msg, dict):
                engine.messages.append(msg)

    # 3. Replay skill loads
    for ev in events:
        if ev["type"] == "skill_auto_loaded":
            name = ev["payload"].get("skill_name", "")
            if name and name not in engine.skill_loader.loaded:
                engine.skill_loader.load_skill(name)

    # 4. Replay plan
    plan_events = [ev for ev in events if ev["type"] in ("plan_created", "plan_task_updated")]
    if plan_events:
        engine.plan_manager.restore_from_events(plan_events)

    # 5. Replay pinned facts
    for ev in events:
        if ev["type"] == "fact_pinned":
            engine.context_mgr.pin_fact(
                ev["payload"].get("fact", ""),
                source_seq=ev.get("seq"),
            )
        elif ev["type"] == "fact_evicted":
            fact_text = ev["payload"].get("fact", "")
            if fact_text:
                engine.context_mgr.forget_fact(fact_text[:20])

    # 6. Derive step count
    step = sum(1 for ev in events if ev["type"] == "tool_finished")

    # 7. Build the runtime
    if runtime_config is None:
        runtime_config = RuntimeConfig()

    runtime = ManagedAgentRuntime(
        session_engine=engine,
        model=model,
        runtime_config=runtime_config,
        access_controller=access_controller,
        cost_tracker=cost_tracker,
        brain=LiteLLMBrain(),
        session_store=SessionStore(),
        archive=archive,
    )

    # 8. Restore session record state
    runtime.session.session_id = session_id
    runtime.session.events = [
        {"type": ev["type"], "timestamp": ev["timestamp"], "payload": ev["payload"]}
        for ev in events
    ]
    runtime.session.state = AgentState(session_meta.get("state", "idle"))
    runtime.session.stop_reason = session_meta.get("stop_reason")
    runtime._step = step
    runtime._current_user_input = user_input

    # 9. Restore pending approval if waiting
    if runtime.session.state == AgentState.WAITING_APPROVAL:
        for ev in reversed(events):
            if ev["type"] == "approval_requested":
                logger.info("Session has pending approval for tool '%s'",
                            ev["payload"].get("tool_name", "unknown"))
                break

    logger.info(
        "Wake complete: step=%d, state=%s, messages=%d, plan_tasks=%d, pinned_facts=%d",
        step,
        runtime.session.state.value,
        len(engine.messages),
        len(engine.plan_manager.tasks),
        len(engine.context_mgr.pinned_facts),
    )

    return runtime
