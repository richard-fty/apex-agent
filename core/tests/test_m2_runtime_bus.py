"""M2 integration tests — runtime publishes typed events to the bus,
emits StreamEnd at terminal transitions, and SharedTurnRunner consumes
from the bus with no archive polling.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent.core.models import PendingApproval, PermissionAction, PermissionDecision, ToolCall
from agent.events import (
    ApprovalRequested,
    AssistantToken,
    ErrorEvent,
    InMemoryEventBus,
    StreamEnd,
    ToolStarted,
    TurnFinished,
    TurnStarted,
    UsageEvent,
)
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.managed_runtime import ManagedAgentRuntime
from agent.runtime.shared_runner import SharedTurnRunner

# Reuse the fakes from test_managed_runtime.
from tests.test_managed_runtime import (
    AllowAccessController,
    AskAccessController,
    FakeBrain,
    FakeSessionEngine,
    _chunk,
)


# ---------------------------------------------------------------------------
# Runtime -> bus: happy path (turn_finished)
# ---------------------------------------------------------------------------


class TestRuntimeBusHappyPath:
    @pytest.mark.asyncio
    async def test_turn_finishes_with_stream_end_completed(self, tmp_path):
        bus = InMemoryEventBus()
        brain = FakeBrain([[
            _chunk(content="hello", usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2,
            )),
        ]])
        runtime = ManagedAgentRuntime(
            session_engine=FakeSessionEngine(),
            model="fake",
            runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
            access_controller=AllowAccessController(),
            brain=brain,
            event_bus=bus,
        )

        # Drain the runtime's yielded ManagedEvents (side-effect: bus publishes).
        guard = RuntimeGuard(runtime.runtime_config)
        async for _ in runtime.start_turn("hi", guard=guard):
            pass

        # Subscribe with since_seq=0 to replay the whole buffered stream.
        collected = []
        async for ev in bus.subscribe(runtime.session.session_id, since_seq=0):
            collected.append(ev)

        # First event is TurnStarted; last event is StreamEnd with final_state=completed.
        assert isinstance(collected[0], TurnStarted)
        assert collected[0].user_input == "hi"
        assert any(isinstance(e, AssistantToken) and e.text == "hello" for e in collected)
        assert any(isinstance(e, UsageEvent) for e in collected)
        assert any(isinstance(e, TurnFinished) for e in collected)
        assert isinstance(collected[-1], StreamEnd)
        assert collected[-1].final_state == "completed"


# ---------------------------------------------------------------------------
# Runtime -> bus: approval path (stream_end=waiting_approval then resume)
# ---------------------------------------------------------------------------


class TestRuntimeBusApprovalFlow:
    @pytest.mark.asyncio
    async def test_stream_end_on_waiting_approval_then_resume(self, tmp_path):
        bus = InMemoryEventBus()
        tool_delta = SimpleNamespace(
            index=0, id="call1",
            function=SimpleNamespace(name="write_file", arguments="{}"),
        )
        brain = FakeBrain([
            [_chunk(tool_calls=[tool_delta], usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2,
            ))],
            # Second LLM call after approval: produce a closing message.
            [_chunk(content="done", usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2,
            ))],
        ])
        runtime = ManagedAgentRuntime(
            session_engine=FakeSessionEngine(),
            model="fake",
            runtime_config=RuntimeConfig(max_steps=4, timeout_seconds=30),
            access_controller=AskAccessController(),
            brain=brain,
            event_bus=bus,
        )

        guard = RuntimeGuard(runtime.runtime_config)
        async for _ in runtime.start_turn("please write", guard=guard):
            pass

        events_round1 = []
        async for ev in bus.subscribe(runtime.session.session_id, since_seq=0):
            events_round1.append(ev)

        assert any(isinstance(e, ApprovalRequested) for e in events_round1)
        assert isinstance(events_round1[-1], StreamEnd)
        assert events_round1[-1].final_state == "waiting_approval"
        last_seq_round1 = events_round1[-1].seq

        # Resume after approval.
        guard2 = RuntimeGuard(runtime.runtime_config)
        async for _ in runtime.resume_pending("approve_once", guard=guard2):
            pass

        events_round2 = []
        async for ev in bus.subscribe(
            runtime.session.session_id, since_seq=last_seq_round1
        ):
            events_round2.append(ev)
        assert isinstance(events_round2[-1], StreamEnd)
        assert events_round2[-1].final_state == "completed"


# ---------------------------------------------------------------------------
# Runtime -> bus: error path emits stream_end(failed)
# ---------------------------------------------------------------------------


class TestRuntimeBusErrorPath:
    @pytest.mark.asyncio
    async def test_resume_without_pending_approval_emits_failed_stream_end(self, tmp_path):
        bus = InMemoryEventBus()
        runtime = ManagedAgentRuntime(
            session_engine=FakeSessionEngine(),
            model="fake",
            runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
            access_controller=AskAccessController(),  # pending is None
            brain=FakeBrain([]),
            event_bus=bus,
        )

        guard = RuntimeGuard(runtime.runtime_config)
        async for _ in runtime.resume_pending("approve_once", guard=guard):
            pass

        events = []
        async for ev in bus.subscribe(runtime.session.session_id, since_seq=0):
            events.append(ev)

        assert any(isinstance(e, ErrorEvent) for e in events)
        assert isinstance(events[-1], StreamEnd)
        assert events[-1].final_state == "failed"


# ---------------------------------------------------------------------------
# SharedTurnRunner: bus-backed stream terminates cleanly (regression test
# for the three race bugs from the previous architecture).
# ---------------------------------------------------------------------------


class TestSharedTurnRunnerNoRace:
    @pytest.mark.asyncio
    async def test_two_consecutive_turns_both_deliver_events(self, tmp_path):
        """Regression: the previous polling design dropped turn 2 entirely.

        With bus-backed streams, each turn is a fresh subscription ending at
        its own StreamEnd. Two sequential turns both deliver their events.
        """
        bus = InMemoryEventBus()
        brain = FakeBrain([
            [_chunk(content="r1", usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2,
            ))],
            [_chunk(content="r2", usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2,
            ))],
        ])
        # Build runner directly so we inject the shared bus + mocked brain.
        from agent.session.archive import SessionArchive
        archive = SessionArchive(db_path=str(tmp_path / "a.db"))
        runner = SharedTurnRunner(
            session_engine=FakeSessionEngine(),
            access_controller=AllowAccessController(),
            cost_tracker=None,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
            archive=archive,
            event_bus=bus,
        )
        runner.runtime.brain = brain

        events1 = [e async for e in runner.start_turn("turn 1")]
        assert any(e.type == "turn_finished" and e.data["content"] == "r1" for e in events1)

        events2 = [e async for e in runner.start_turn("turn 2")]
        assert any(e.type == "turn_finished" and e.data["content"] == "r2" for e in events2), \
            "Turn 2 must emit turn_finished (this was broken under the old polling design)"
