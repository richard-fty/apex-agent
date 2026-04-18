"""Session orchestration above the managed runtime.

The orchestrator owns RuntimeGuard creation (limits live above the harness),
session lifecycle queries, and delegates recovery to ``wake()`` so there is
exactly one code path that rebuilds a harness from the event log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from agent.runtime.managed_runtime import ManagedAgentRuntime, ManagedEvent
from agent.runtime.wake import wake
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
    above the harness rather than inside it (Gap 8). Recovery/resume always
    delegates to ``wake()`` so there is a single reconstruction path.
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
        """Resume a session by delegating to ``wake()``.

        The orchestrator provides the archive and the caller provides a fresh
        session engine; ``wake`` reconstructs messages, skills, and pending
        approvals from the durable event log.
        """
        runtime = wake(
            self.archive,
            session_id,
            runtime_config=runtime_config,
            access_controller=access_controller,
            cost_tracker=cost_tracker,
        )
        return SessionHandle(session_id=session_id, runtime=runtime)
