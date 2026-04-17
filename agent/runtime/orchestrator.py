"""Session orchestration above the managed runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runtime.managed_runtime import ManagedAgentRuntime
from agent.session.store import SessionStore
from agent.runtime.guards import RuntimeConfig


@dataclass
class SessionHandle:
    session_id: str
    runtime: ManagedAgentRuntime


class SessionOrchestrator:
    """Control-plane style helper for creating, replaying, and resuming sessions."""

    def __init__(self, session_store: SessionStore | None = None) -> None:
        self.session_store = session_store or SessionStore()

    def create_runtime(
        self,
        *,
        session_engine: Any,
        model: str,
        runtime_config: RuntimeConfig,
        access_controller: Any | None = None,
        cost_tracker: Any | None = None,
    ) -> SessionHandle:
        runtime = ManagedAgentRuntime(
            session_engine=session_engine,
            model=model,
            runtime_config=runtime_config,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
            session_store=self.session_store,
        )
        return SessionHandle(session_id=runtime.session.session_id, runtime=runtime)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        return self.session_store.load(session_id)

    def replay_events(self, session_id: str) -> list[dict[str, Any]]:
        record = self.load_session(session_id)
        if record is None:
            return []
        return record.get("events", [])

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
    ) -> SessionHandle:
        runtime = ManagedAgentRuntime(
            session_engine=session_engine,
            model=model,
            runtime_config=runtime_config,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
            session_store=self.session_store,
        )
        record = self.load_session(session_id)
        if record is None:
            raise ValueError(f"Unknown session: {session_id}")

        runtime.session.session_id = session_id
        runtime.session.events = list(record.get("events", []))
        runtime.session.stop_reason = record.get("stop_reason")
        runtime.session.metadata = dict(record.get("metadata", {}))
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
