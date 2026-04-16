from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from agent.runtime.managed_runtime import LiteLLMBrain, ManagedAgentRuntime
from agent.core.models import (
    PendingApproval,
    PermissionAction,
    PermissionDecision,
    ToolCall,
)
from agent.runtime.orchestrator import SessionOrchestrator
from agent.session.store import SessionStore
from harness.runtime import RuntimeConfig
from harness.trace import Trace


class FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "FakeStream":
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _chunk(*, content: str | None = None, tool_calls: list[Any] | None = None, usage: Any = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice], usage=usage)


class FakeBrain(LiteLLMBrain):
    def __init__(self, streams: list[list[Any]]) -> None:
        self.streams = streams

    async def complete(self, *, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], stream: bool) -> Any:
        return FakeStream(self.streams.pop(0))


@dataclass
class FakeRetrieval:
    used: bool = False
    route: str = "default"
    evidence: Any = None


@dataclass
class FakePrepared:
    messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    retrieval: FakeRetrieval


class FakeDispatch:
    def __init__(self) -> None:
        self.tool_names = ["read_file", "write_file"]

    def parse_tool_calls(self, raw_tool_calls: list[dict[str, Any]]) -> list[Any]:
        return [
            ToolCall(
                id=raw["id"],
                name=raw["function"]["name"],
                arguments={"path": "tmp.txt", "content": "hello"},
            )
            for raw in raw_tool_calls
        ]

    def validate_call(self, tool_call: Any) -> str | None:
        return None

    def get_tool_def(self, name: str) -> Any:
        return SimpleNamespace(name=name, is_read_only=name == "read_file", is_networked=False, requires_confirmation=name != "read_file", is_destructive=False)

    async def execute(self, tool_call: Any) -> Any:
        return SimpleNamespace(content=f"executed:{tool_call.name}", success=True)

    def retry_prompt(self, tool_call: Any, error: str) -> str:
        return f"Please fix arguments for {tool_call.name}: {error}"


class FakeSkillLoader:
    def get_available_skill_names(self) -> list[str]:
        return []

    def get_loaded_skill_names(self) -> list[str]:
        return []


class FakeContextManager:
    def compact_tool_result(self, content: str) -> str:
        return content


class FakeSessionEngine:
    def __init__(self) -> None:
        self.context_strategy = "truncate"
        self.dispatch = FakeDispatch()
        self.skill_loader = FakeSkillLoader()
        self.context_mgr = FakeContextManager()
        self.messages: list[dict[str, Any]] = []

    def pre_load_for_input(self, user_input: str) -> list[str]:
        return []

    def add_user_message(self, user_input: str) -> None:
        self.messages.append({"role": "user", "content": user_input})

    def add_assistant_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def add_tool_message(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append({"role": "tool", "name": name, "content": content})

    def rebuild_system_prompt(self) -> None:
        return None

    async def prepare_for_model(self, user_input: str) -> FakePrepared:
        return FakePrepared(messages=self.messages, tool_schemas=[], retrieval=FakeRetrieval())


class AskAccessController:
    pending = None

    def evaluate(self, tool_call: Any, tool_def: Any) -> PermissionDecision:
        return PermissionDecision(
            action=PermissionAction.ASK,
            reason="approval required",
            rule_source="test",
            requires_user_input=True,
        )

    def create_pending(self, tool_call: Any, decision: PermissionDecision) -> Any:
        self.pending = PendingApproval(tool_call=tool_call, decision=decision)
        return self.pending

    def resolve_pending(self, action: str) -> PermissionDecision:
        self.pending = None
        return PermissionDecision(action=PermissionAction.ALLOW, reason="approved", rule_source="test")

    def record_allow(self, tool_name: str) -> None:
        return None


class AllowAccessController(AskAccessController):
    def evaluate(self, tool_call: Any, tool_def: Any) -> PermissionDecision:
        return PermissionDecision(action=PermissionAction.ALLOW, reason="ok", rule_source="test")


def test_managed_runtime_persists_completed_session(tmp_path) -> None:
    brain = FakeBrain([[ _chunk(content="done", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)) ]])
    runtime = ManagedAgentRuntime(
        session_engine=FakeSessionEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )
    trace = Trace(run_id="r1", model="fake-model", scenario="core_agent", prompt="hello", context_strategy="truncate")

    import asyncio
    asyncio.run(runtime.run_to_completion(user_input="hello", trace=trace))

    record = runtime.session_store.load(runtime.session.session_id)
    assert record is not None
    assert record["state"] == "completed"
    assert trace.final_output == "done"


def test_managed_runtime_pauses_for_approval(tmp_path) -> None:
    tool_delta = SimpleNamespace(index=0, id="call1", function=SimpleNamespace(name="write_file", arguments="{}"))
    brain = FakeBrain([[ _chunk(tool_calls=[tool_delta], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)) ]])
    runtime = ManagedAgentRuntime(
        session_engine=FakeSessionEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AskAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )

    import asyncio

    async def collect() -> list[str]:
        events = []
        async for event in runtime.start_turn("write something"):
            events.append(event.type)
        return events

    events = asyncio.run(collect())
    record = runtime.session_store.load(runtime.session.session_id)
    assert "approval_requested" in events
    assert record is not None
    assert record["state"] == "waiting_approval"


def test_managed_runtime_cancel_persists_cancelled_state(tmp_path) -> None:
    runtime = ManagedAgentRuntime(
        session_engine=FakeSessionEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=FakeBrain([]),
        session_store=SessionStore(str(tmp_path)),
    )
    runtime.cancel()
    record = runtime.session_store.load(runtime.session.session_id)
    assert record is not None
    assert record["state"] == "cancelled"


def test_orchestrator_replays_persisted_events(tmp_path) -> None:
    store = SessionStore(str(tmp_path))
    orchestrator = SessionOrchestrator(store)
    handle = orchestrator.create_runtime(
        session_engine=FakeSessionEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AllowAccessController(),
        cost_tracker=None,
    )
    handle.runtime.session.append_event("custom", note="hello")
    handle.runtime._persist_session()

    events = orchestrator.replay_events(handle.session_id)
    assert events
    assert events[-1]["type"] == "custom"


def test_orchestrator_resume_runtime_rehydrates_messages(tmp_path) -> None:
    store = SessionStore(str(tmp_path))
    orchestrator = SessionOrchestrator(store)
    runtime = ManagedAgentRuntime(
        session_engine=FakeSessionEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=FakeBrain([]),
        session_store=store,
    )
    runtime.session.append_event("user_message_added", message={"role": "user", "content": "hello"})
    runtime.session.append_event("assistant_message_added", message={"role": "assistant", "content": "world"})
    runtime._persist_session()

    restored_engine = FakeSessionEngine()
    handle = orchestrator.resume_runtime(
        session_id=runtime.session.session_id,
        session_engine=restored_engine,
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AllowAccessController(),
    )

    assert handle.session_id == runtime.session.session_id
    assert restored_engine.messages[0]["content"] == "hello"
    assert restored_engine.messages[1]["content"] == "world"


class MalformedDispatch(FakeDispatch):
    def __init__(self) -> None:
        super().__init__()
        self._calls = 0

    def validate_call(self, tool_call: Any) -> str | None:
        self._calls += 1
        if self._calls == 1:
            return "Missing required parameters: path"
        return None


class FailingDispatch(FakeDispatch):
    async def execute(self, tool_call: Any) -> Any:
        return SimpleNamespace(content="Error: File not found", success=False)


class FailingSessionEngine(FakeSessionEngine):
    def __init__(self, dispatch: FakeDispatch) -> None:
        super().__init__()
        self.dispatch = dispatch


def test_managed_runtime_records_malformed_recovery(tmp_path) -> None:
    tool_delta = SimpleNamespace(index=0, id="call1", function=SimpleNamespace(name="read_file", arguments="{}"))
    brain = FakeBrain([
        [_chunk(tool_calls=[tool_delta], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))],
        [_chunk(content="done", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))],
    ])
    engine = FailingSessionEngine(MalformedDispatch())
    runtime = ManagedAgentRuntime(
        session_engine=engine,
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=4, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )
    trace = Trace(run_id="r_mal", model="fake-model", scenario="core_agent", prompt="read", context_strategy="truncate")

    import asyncio
    asyncio.run(runtime.run_to_completion(user_input="read it", trace=trace))

    assert trace.recovery_events, "trace should record the malformed-argument repair hint"
    assert trace.recovery_events[0]["kind"] == "malformed_arguments"


def test_managed_runtime_records_tool_execution_failure(tmp_path) -> None:
    tool_delta = SimpleNamespace(index=0, id="call1", function=SimpleNamespace(name="read_file", arguments="{}"))
    brain = FakeBrain([
        [_chunk(tool_calls=[tool_delta], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))],
        [_chunk(content="recovered", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))],
    ])
    engine = FailingSessionEngine(FailingDispatch())
    runtime = ManagedAgentRuntime(
        session_engine=engine,
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=4, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )
    trace = Trace(run_id="r_fail", model="fake-model", scenario="core_agent", prompt="read", context_strategy="truncate")

    import asyncio
    asyncio.run(runtime.run_to_completion(user_input="read it", trace=trace))

    assert trace.recovery_events
    assert any(ev["kind"] == "tool_execution_failed" for ev in trace.recovery_events)


def test_managed_runtime_records_approval_decisions(tmp_path) -> None:
    tool_delta = SimpleNamespace(index=0, id="call1", function=SimpleNamespace(name="write_file", arguments="{}"))
    brain = FakeBrain([[_chunk(tool_calls=[tool_delta], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))]])
    runtime = ManagedAgentRuntime(
        session_engine=FakeSessionEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=4, timeout_seconds=30),
        access_controller=AskAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )
    trace = Trace(run_id="r_ask", model="fake-model", scenario="core_agent", prompt="write", context_strategy="truncate")

    import asyncio
    asyncio.run(runtime.run_to_completion(user_input="write something", trace=trace))

    assert trace.approval_decisions
    assert trace.approval_decisions[0]["action"] == "ask"
    assert trace.approval_decisions[0]["tool_name"] == "write_file"
    assert trace.stop_reason is not None
    assert "approval" in trace.stop_reason.lower()


def test_managed_runtime_records_retrieval_injection(tmp_path) -> None:
    brain = FakeBrain([[_chunk(content="done", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))]])

    class RetrievalEngine(FakeSessionEngine):
        async def prepare_for_model(self, user_input: str) -> FakePrepared:
            evidence = SimpleNamespace(items=["a", "b"], used_local=True, used_web=False, stages=[])
            retrieval = FakeRetrieval(used=True, route="research", evidence=evidence)
            return FakePrepared(messages=self.messages, tool_schemas=[], retrieval=retrieval)

    runtime = ManagedAgentRuntime(
        session_engine=RetrievalEngine(),
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=2, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )
    trace = Trace(run_id="r_ret", model="fake-model", scenario="core_agent", prompt="research", context_strategy="truncate")

    import asyncio
    asyncio.run(runtime.run_to_completion(user_input="look it up", trace=trace))

    assert trace.retrieval_injections
    first = trace.retrieval_injections[0]
    assert first["used"] is True
    assert first["route"] == "research"
    assert first["item_count"] == 2


def test_runtime_guard_surfaces_timeout_stop_reason() -> None:
    from harness.runtime import RuntimeConfig as _RC, RuntimeGuard as _RG
    import time as _time

    guard = _RG(_RC(max_steps=100, timeout_seconds=0))
    _time.sleep(0.01)
    err = guard.check()
    assert err is not None
    assert "timeout" in err.lower()


def test_runtime_guard_surfaces_step_limit_stop_reason() -> None:
    from harness.runtime import RuntimeConfig as _RC, RuntimeGuard as _RG

    guard = _RG(_RC(max_steps=1, timeout_seconds=30))
    guard.increment_step()
    err = guard.check()
    assert err is not None
    assert "step limit" in err.lower()


def test_runtime_guard_surfaces_cancellation_stop_reason() -> None:
    from harness.runtime import RuntimeConfig as _RC, RuntimeGuard as _RG

    guard = _RG(_RC(max_steps=10, timeout_seconds=30))
    guard.cancel()
    err = guard.check()
    assert err is not None
    assert "cancelled" in err.lower()


class UnknownToolDispatch(FakeDispatch):
    def get_tool_def(self, name: str) -> Any:
        return None


def test_managed_runtime_records_unknown_tool(tmp_path) -> None:
    tool_delta = SimpleNamespace(index=0, id="call1", function=SimpleNamespace(name="nope", arguments="{}"))
    brain = FakeBrain([
        [_chunk(tool_calls=[tool_delta], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))],
        [_chunk(content="stopped", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))],
    ])
    engine = FailingSessionEngine(UnknownToolDispatch())
    runtime = ManagedAgentRuntime(
        session_engine=engine,
        model="fake-model",
        runtime_config=RuntimeConfig(max_steps=4, timeout_seconds=30),
        access_controller=AllowAccessController(),
        brain=brain,
        session_store=SessionStore(str(tmp_path)),
    )
    trace = Trace(run_id="r_unk", model="fake-model", scenario="core_agent", prompt="x", context_strategy="truncate")

    import asyncio
    asyncio.run(runtime.run_to_completion(user_input="do something", trace=trace))

    assert any(ev["kind"] == "unknown_tool" for ev in trace.recovery_events)
