"""Session orchestration above the managed runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from agent.core.models import AgentState, PendingApproval
from agent.runtime.managed_runtime import ManagedAgentRuntime, ManagedEvent
from agent.session.archive import SessionArchive
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.sandbox import BaseSandbox


@dataclass
class SessionHandle:
    session_id: str
    runtime: ManagedAgentRuntime


class SessionOrchestrator:
    """Control-plane for creating, replaying, and resuming sessions.

    The orchestrator owns RuntimeGuard creation so limit enforcement sits
    above the harness rather than inside it (Gap 8).
    """

    def __init__(
        self,
        archive: SessionArchive | None = None,
    ) -> None:
        self.archive = archive or SessionArchive()

    def create_runtime(
        self,
        *,
        session_engine: Any,
        model: str,
        runtime_config: RuntimeConfig,
        access_controller: Any | None = None,
        cost_tracker: Any | None = None,
        archive: SessionArchive | None = None,
        sandbox: BaseSandbox | None = None,
        event_bus: Any | None = None,
        session_id: str | None = None,
    ) -> SessionHandle:
        runtime = ManagedAgentRuntime(
            session_engine=session_engine,
            model=model,
            runtime_config=runtime_config,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
            archive=archive or self.archive,
            sandbox=sandbox,
            event_bus=event_bus,
            session_id=session_id,
        )
        return SessionHandle(session_id=runtime.session.session_id, runtime=runtime)

    async def run_turn(
        self,
        handle: SessionHandle,
        user_input: str,
    ) -> AsyncIterator[ManagedEvent]:
        """Run one turn with a guard created here so limits are orchestrator-owned."""
        guard = RuntimeGuard(handle.runtime.runtime_config)
        async for event in handle.runtime.start_turn(user_input, guard=guard):
            yield event

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        return self.archive.load_session(session_id)

    def replay_events(self, session_id: str) -> list[dict[str, Any]]:
        return self.archive.get_events(session_id)

    def get_session_state(self, session_id: str) -> str | None:
        record = self.load_session(session_id)
        if record is None:
            return None
        return record.get("state")

    def resume_runtime(
        self,
        *,
        session_id: str,
        session_engine: Any,
        model: str,
        runtime_config: RuntimeConfig,
        access_controller: Any | None = None,
        cost_tracker: Any | None = None,
        sandbox: BaseSandbox | None = None,
    ) -> SessionHandle:
        events = self.replay_events(session_id)
        record = self.load_session(session_id)
        if record is None:
            raise ValueError(f"Unknown session: {session_id}")

        metadata = record.get("metadata", {}) or {}
        session_metadata = metadata.get("session_metadata", {})
        runtime_state = metadata.get("runtime_state", {})

        runtime = ManagedAgentRuntime(
            session_engine=session_engine,
            model=model,
            runtime_config=runtime_config,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
            archive=self.archive,
            session_id=session_id,
            sandbox=sandbox,
        )
        runtime.session.events = list(events)
        runtime.session.state = AgentState(record.get("state", "idle"))
        runtime.session.stop_reason = record.get("stop_reason")
        runtime.session.metadata = dict(session_metadata or record.get("metadata", {}))
        runtime.session.step = int(runtime_state.get("step", sum(1 for event in events if event.get("type") == "tool_finished")))
        runtime.session.current_user_input = runtime_state.get("current_user_input")
        runtime.session.metadata["cancel_requested"] = bool(runtime_state.get("cancel_requested", False))
        pending_snapshot = runtime_state.get("pending_approval")
        if pending_snapshot is not None:
            runtime.session.pending_approval = PendingApproval.model_validate(pending_snapshot)
            if access_controller is not None and hasattr(access_controller, "pending"):
                access_controller.pending = runtime.session.pending_approval
        self._rehydrate_session_engine(session_engine, runtime.session.events)
        return SessionHandle(session_id=session_id, runtime=runtime)

    def _rehydrate_session_engine(self, session_engine: Any, events: list[dict[str, Any]]) -> None:
        for event in events:
            payload = event.get("payload", {})
            if event.get("type") == "user_message_added":
                message = payload.get("message", {})
                if message.get("content"):
                    session_engine.add_user_message(message["content"])
            elif event.get("type") == "assistant_message_added":
                message = payload.get("message")
                if message:
                    session_engine.add_assistant_message(message)
            elif event.get("type") == "tool_message_added":
                message = payload.get("message", {})
                if message:
                    session_engine.add_tool_message(
                        message.get("tool_call_id", "restored"),
                        message.get("name", "tool"),
                        message.get("content", ""),
                    )
