"""Wake — rebuild a ManagedAgentRuntime from the session archive.

Implements the `wake(session_id)` contract: a fresh stateless harness can
resume any session by replaying its event log, including full rehydration of
pending approvals (Gap 3).

Usage:
    archive = SessionArchive("results/sessions/archive.db")
    runtime = wake(archive, "session-abc-123", model="deepseek-chat", ...)
    guard = RuntimeGuard(RuntimeConfig())
    async for event in runtime.start_turn("resume", guard=guard):
        ...
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from typing import Any

from agent.core.models import (
    AgentState,
    PendingApproval,
    PermissionAction,
    PermissionDecision,
    ToolCall,
)
from agent.runtime.guards import RuntimeConfig
from agent.runtime.managed_runtime import (
    LiteLLMBrain,
    ManagedAgentRuntime,
)
from agent.session.archive import SessionArchive
from agent.session.engine import SessionEngine

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
    metadata = session_meta.get("metadata", {}) or {}
    session_metadata = metadata.get("session_metadata", {})
    runtime_state = metadata.get("runtime_state", {})

    logger.info("Waking session %s: %d events, model=%s", session_id, len(events), model)

    # 1. Rebuild SessionEngine with tools registered
    engine = SessionEngine(
        model=model,
        context_strategy=context_strategy,
        archive=archive,
        session_id=session_id,
    )

    # 2. Replay messages from events
    user_input = runtime_state.get("current_user_input")
    for ev in events:
        etype = ev["type"]
        payload = ev["payload"]

        if etype == "user_message_added":
            msg = payload.get("message", payload)
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            engine.messages.append({"role": "user", "content": content})
        elif etype == "user_input_received" and not user_input:
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

    # 6. Restore persisted runtime state, with event-derived fallbacks.
    step = int(runtime_state.get("step", sum(1 for ev in events if ev["type"] == "tool_finished")))
    pending_snapshot = runtime_state.get("pending_approval")

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
        archive=archive,
        session_id=session_id,
    )

    # 8. Restore session record state
    runtime.session.session_id = session_id
    runtime.session.events = [
        {"type": ev["type"], "timestamp": ev["timestamp"], "payload": ev["payload"]}
        for ev in events
    ]
    runtime.session.state = AgentState(session_meta.get("state", "idle"))
    runtime.session.stop_reason = session_meta.get("stop_reason")
    runtime.session.metadata = session_metadata or {
        "model": model,
        "context_strategy": context_strategy,
    }
    runtime.session.step = step
    runtime.session.current_user_input = user_input
    runtime.session.metadata["cancel_requested"] = bool(runtime_state.get("cancel_requested", False))

    # 9. Fully rehydrate pending approval when session was paused for one
    if runtime.session.state == AgentState.WAITING_APPROVAL:
        pending = None
        if pending_snapshot:
            try:
                restored = PendingApproval.model_validate(pending_snapshot)
                if access_controller is not None:
                    pending = access_controller.create_pending(restored.tool_call, restored.decision)
                    pending.options = restored.options
                    pending.created_at = restored.created_at
                else:
                    pending = restored
            except Exception:
                logger.warning("Failed to restore pending approval snapshot; falling back to event replay", exc_info=True)

        if pending is None:
            pending_tool_name: str | None = None
            pending_reason: str = "Approval required"

            for ev in reversed(events):
                if ev["type"] == "approval_requested":
                    pending_tool_name = ev["payload"].get("tool_name")
                    pending_reason = ev["payload"].get("reason", pending_reason)
                    break

            if pending_tool_name and access_controller is not None:
                # Reconstruct the ToolCall from the last assistant message that
                # contained a call to this tool, so resume_pending() has full args.
                for ev in reversed(events):
                    if ev["type"] == "assistant_message_added":
                        msg = ev["payload"].get("message", {})
                        if isinstance(msg, dict):
                            for tc in (msg.get("tool_calls") or []):
                                if isinstance(tc, dict) and tc.get("function", {}).get("name") == pending_tool_name:
                                    try:
                                        args = _json.loads(tc["function"].get("arguments", "{}"))
                                    except Exception:
                                        args = {}
                                    tool_call = ToolCall(
                                        id=tc.get("id", str(uuid.uuid4())),
                                        name=pending_tool_name,
                                        arguments=args,
                                    )
                                    decision = PermissionDecision(
                                        action=PermissionAction.ASK,
                                        reason=pending_reason,
                                        rule_source="wake.rehydrated",
                                    )
                                    pending = access_controller.create_pending(tool_call, decision)
                                    logger.info(
                                        "Rehydrated pending approval for tool '%s' (args=%s)",
                                        pending_tool_name,
                                        list(args.keys()),
                                    )
                                    break
                        break
            elif pending_tool_name:
                logger.warning(
                    "Session has pending approval for '%s' but no access_controller provided; "
                    "call resume_pending() manually after attaching one.",
                    pending_tool_name,
                )

        runtime.session.pending_approval = pending

    logger.info(
        "Wake complete: step=%d, state=%s, messages=%d, plan_tasks=%d, pinned_facts=%d",
        step,
        runtime.session.state.value,
        len(engine.messages),
        len(engine.plan_manager.tasks),
        len(engine.context_mgr.pinned_facts),
    )

    return runtime
