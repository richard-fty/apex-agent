"""T3 Apex Extensions regression tests.

These guard the apex-specific layer against regressions. Organized as the
eval-suite.md defines it, one test group per T3 claim:

T3.1  skill_pack_preload_by_intent
T3.2  retrieval_policy_routing
T3.3  approval_allow_ask_deny
T3.4  trace_richness

Failure semantics: no metric here may drop > 5 % vs. previous release.
In unit-test form this means: all assertions must pass at every release cut.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from agent.core.models import (
    PermissionAction,
    PermissionMode,
    ToolCall,
    ToolDef,
    ToolGroup,
    ToolLoadingStrategy,
)
from agent.policy.access_control import AccessController
from agent.policy.permission_policy import PermissionPolicyEngine
from agent.policy.policy_models import AccessPolicy, POLICY_DEFAULT, POLICY_AUTO
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.managed_runtime import LiteLLMBrain, ManagedAgentRuntime
from agent.runtime.tool_dispatch import ToolDispatch
from agent.runtime.trace import Trace
from agent.session.archive import SessionArchive


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_t1 pattern)
# ---------------------------------------------------------------------------

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


def _usage() -> Any:
    return SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)


class FakeBrain(LiteLLMBrain):
    def __init__(self, streams: list[list[Any]]) -> None:
        self.streams = streams

    async def complete(self, *, model, messages, tools, stream) -> Any:
        return FakeStream(self.streams.pop(0))


_KNOWN_TOOLS = {"write_file", "read_file"}


class FakeDispatch:
    def __init__(self) -> None:
        self.tool_names: list[str] = list(_KNOWN_TOOLS)

    def parse_tool_calls(self, raw: list[dict]) -> list[Any]:
        from agent.core.models import ToolCall
        return [ToolCall(id=r["id"], name=r["function"]["name"], arguments={}) for r in raw]

    def validate_call(self, tc: Any) -> str | None:
        return None

    def get_tool_def(self, name: str) -> Any:
        if name not in _KNOWN_TOOLS:
            return None
        is_read_only = name == "read_file"
        return SimpleNamespace(
            name=name,
            is_read_only=is_read_only,
            is_networked=False,
            requires_confirmation=not is_read_only,
            is_destructive=False,
            mutates_state=not is_read_only,
            shell_command_arg=None,
            path_access=None,
        )

    async def execute(self, tc: Any) -> Any:
        return SimpleNamespace(content=f"result_of_{tc.name}", success=True)

    def retry_prompt(self, tc: Any, err: str) -> str:
        return f"fix: {err}"


class FakeContextMgr:
    def compact_tool_result(self, c: str) -> str:
        return c


class FakeSkillLoader:
    def __init__(self) -> None:
        self._loaded: list[str] = []
        self._available: list[str] = ["stock_strategy", "research"]

    def get_available_skill_names(self) -> list[str]:
        return self._available

    def get_loaded_skill_names(self) -> list[str]:
        return list(self._loaded)

    def load_skill(self, name: str) -> None:
        if name not in self._loaded:
            self._loaded.append(name)


class IntentAwareEngine:
    """Session engine that pre-loads skills based on keyword matching."""

    def __init__(self, keyword_map: dict[str, str]) -> None:
        self.context_strategy = "truncate"
        self.dispatch = FakeDispatch()
        self.skill_loader = FakeSkillLoader()
        self.context_mgr = FakeContextMgr()
        self.messages: list[dict] = []
        self._keyword_map = keyword_map  # keyword → skill_name

    def pre_load_for_input(self, user_input: str) -> list[str]:
        loaded = []
        lower = user_input.lower()
        for kw, skill_name in self._keyword_map.items():
            if kw in lower and skill_name not in self.skill_loader._loaded:
                self.skill_loader.load_skill(skill_name)
                loaded.append(skill_name)
        return loaded

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, msg: dict) -> None:
        self.messages.append(msg)

    def add_tool_message(self, tid: str, name: str, content: str) -> None:
        self.messages.append({"role": "tool", "name": name, "content": content})

    def rebuild_system_prompt(self) -> None:
        pass

    async def prepare_for_model(self, user_input: str) -> Any:
        retrieval = SimpleNamespace(used=False, route="default", evidence=None)
        return SimpleNamespace(messages=self.messages, tool_schemas=[], retrieval=retrieval)


# ---------------------------------------------------------------------------
# T3.1 — skill_pack_preload_by_intent
# Spec: user input matching a pack's keywords triggers pre-load before first
# LLM call; pack's tools are available in turn 1.
# ---------------------------------------------------------------------------

class TestT31SkillPackPreload:

    def test_matching_keyword_triggers_preload(self, tmp_path) -> None:
        """Input containing 'stock' triggers pre-load of 'stock_strategy' skill."""
        engine = IntentAwareEngine({"stock": "stock_strategy", "research": "research"})
        brain = FakeBrain([[_chunk(content="analysis complete", usage=_usage())]])
        archive = SessionArchive(db_path=str(tmp_path / "arc.db"))

        rt = ManagedAgentRuntime(
            session_engine=engine,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
            brain=brain,
            archive=archive,
        )

        pre_loaded: list[str] = []

        async def run():
            async for ev in rt.start_turn("analyze stock prices for AAPL", guard=RuntimeGuard(rt.runtime_config)):
                if ev.type == "skill_auto_loaded":
                    pre_loaded.append(ev.data["skill_name"])

        asyncio.run(run())

        assert "stock_strategy" in pre_loaded, (
            "stock_strategy must be pre-loaded for stock-related input"
        )

    def test_unrelated_input_does_not_preload(self, tmp_path) -> None:
        """Input with no matching keywords must not pre-load any skill."""
        engine = IntentAwareEngine({"stock": "stock_strategy"})
        brain = FakeBrain([[_chunk(content="hello", usage=_usage())]])
        archive = SessionArchive(db_path=str(tmp_path / "arc.db"))

        rt = ManagedAgentRuntime(
            session_engine=engine,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
            brain=brain,
            archive=archive,
        )

        pre_loaded: list[str] = []

        async def run():
            async for ev in rt.start_turn("tell me a joke", guard=RuntimeGuard(rt.runtime_config)):
                if ev.type == "skill_auto_loaded":
                    pre_loaded.append(ev.data["skill_name"])

        asyncio.run(run())

        assert pre_loaded == [], f"No skill should be pre-loaded, got {pre_loaded}"

    def test_preload_event_is_persisted_to_archive(self, tmp_path) -> None:
        """skill_auto_loaded events must be written to the archive for replay."""
        engine = IntentAwareEngine({"research": "research"})
        brain = FakeBrain([[_chunk(content="done", usage=_usage())]])
        archive = SessionArchive(db_path=str(tmp_path / "arc.db"))

        rt = ManagedAgentRuntime(
            session_engine=engine,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
            brain=brain,
            archive=archive,
        )

        async def run():
            async for _ in rt.start_turn("research the topic thoroughly", guard=RuntimeGuard(rt.runtime_config)):
                pass

        asyncio.run(run())

        events = archive.get_events(rt.session.session_id)
        preload_events = [e for e in events if e["type"] == "skill_auto_loaded"]
        assert len(preload_events) >= 1, (
            "skill_auto_loaded events must be persisted to archive for replay"
        )


# ---------------------------------------------------------------------------
# T3.2 — retrieval_policy_routing
# Spec: retrieval-intent → evaluate returns evidence; ingest-intent →
# runtime tools surfaced; out-of-scope → no retrieval, no tools.
# ---------------------------------------------------------------------------

class TestT32RetrievalPolicyRouting:
    """Test retrieval policy hint detection without requiring a live RAG service."""

    def _make_policy(self):
        """Import ResearchPolicy and test only its routing logic."""
        from services.retrieval_policy import ResearchPolicy
        return ResearchPolicy

    def test_retrieval_hints_trigger_retrieval_route(self) -> None:
        """Inputs with retrieval keywords hit the _should_attempt_retrieval path."""
        from services.retrieval_policy import _should_attempt_retrieval_for

        # Must be > 12 chars per the policy's length guard
        for hint in ["what is the project status", "explain this concept", "summarize the document"]:
            assert _should_attempt_retrieval_for(hint), (
                f"'{hint}' should trigger retrieval but did not"
            )

    def test_ingest_hints_trigger_ingest_route(self) -> None:
        """Inputs with ingest keywords route to the ingest path."""
        from services.retrieval_policy import _INGEST_HINTS, _should_ingest_for

        for hint in ["index this", "ingest the document", "add to knowledge base"]:
            assert _should_ingest_for(hint), (
                f"'{hint}' should trigger ingest but did not"
            )

    def test_out_of_scope_input_does_not_trigger_retrieval(self) -> None:
        """Short greetings and unambiguous direct questions do not trigger retrieval."""
        from services.retrieval_policy import _should_attempt_retrieval_for

        for text in ["hello", "2 + 2", ""]:
            assert not _should_attempt_retrieval_for(text), (
                f"'{text}' should NOT trigger retrieval"
            )

    def test_web_first_hints_set_prefer_web_flag(self) -> None:
        """'latest', 'news', 'current' etc. trigger prefer_web=True."""
        from services.retrieval_policy import _should_prefer_web_for

        for hint in ["latest news", "recent changes", "current state"]:
            assert _should_prefer_web_for(hint), (
                f"'{hint}' should prefer web search but did not"
            )


# ---------------------------------------------------------------------------
# T3.3 — approval_allow_ask_deny
# Spec: read-only → allow; destructive → ask; denied → blocks and run replans.
# ---------------------------------------------------------------------------

class TestT33ApprovalAllowAskDeny:

    def _engine(self) -> PermissionPolicyEngine:
        return PermissionPolicyEngine()

    def _tool_def(self, *, is_read_only=False, is_destructive=False, requires_confirmation=False) -> Any:
        return SimpleNamespace(
            name="test_tool",
            is_read_only=is_read_only,
            is_destructive=is_destructive,
            is_networked=False,
            requires_confirmation=requires_confirmation,
            mutates_state=not is_read_only,
            shell_command_arg=None,
            path_access=None,
        )

    def _tc(self, name: str = "test_tool") -> ToolCall:
        return ToolCall(id="t1", name=name, arguments={})

    def test_read_only_tool_is_allowed(self) -> None:
        """Read-only local tool must get ALLOW in DEFAULT mode."""
        engine = self._engine()
        policy = POLICY_DEFAULT
        td = self._tool_def(is_read_only=True)
        tc = self._tc()

        decision = engine.evaluate(policy, [], {}, [], tc, td)

        assert decision.action == PermissionAction.ALLOW, (
            f"Read-only tool must be ALLOW, got {decision.action} ({decision.reason})"
        )

    def test_destructive_tool_requires_ask(self) -> None:
        """Destructive tool must get ASK regardless of mode."""
        engine = self._engine()
        policy = POLICY_DEFAULT
        td = self._tool_def(is_destructive=True)
        tc = self._tc()

        decision = engine.evaluate(policy, [], {}, [], tc, td)

        assert decision.action == PermissionAction.ASK, (
            f"Destructive tool must be ASK, got {decision.action} ({decision.reason})"
        )

    def test_blocked_tool_is_denied(self) -> None:
        """Tool in policy.blocked_tools must get DENY."""
        engine = self._engine()
        policy = AccessPolicy(mode=PermissionMode.DEFAULT, blocked_tools={"dangerous_tool"})
        td = self._tool_def()
        tc = self._tc("dangerous_tool")

        decision = engine.evaluate(policy, [], {}, [], tc, td)

        assert decision.action == PermissionAction.DENY, (
            f"Blocked tool must be DENY, got {decision.action}"
        )

    def test_requires_confirmation_tool_triggers_ask(self) -> None:
        """Tool with requires_confirmation=True must get ASK in default mode."""
        engine = self._engine()
        policy = POLICY_DEFAULT
        td = self._tool_def(requires_confirmation=True)
        tc = self._tc()

        decision = engine.evaluate(policy, [], {}, [], tc, td)

        assert decision.action == PermissionAction.ASK, (
            f"requires_confirmation tool must be ASK, got {decision.action}"
        )

    def test_plan_mode_blocks_write_tools(self) -> None:
        """In PLAN mode, non-read-only tools are denied (plan = read-only exploration)."""
        engine = self._engine()
        from agent.policy.policy_models import POLICY_PLAN
        td = self._tool_def(is_read_only=False)
        tc = self._tc()

        decision = engine.evaluate(POLICY_PLAN, [], {}, [], tc, td)

        assert decision.action == PermissionAction.DENY, (
            f"Non-read-only tool must be DENY in PLAN mode, got {decision.action}"
        )

    def test_denied_tool_does_not_execute(self, tmp_path) -> None:
        """When access controller returns DENY, no tool execution occurs."""
        from agent.core.models import PermissionDecision
        from agent.policy.access_control import AccessController

        class DenyAll(AccessController):
            def evaluate(self, tc, td):
                return PermissionDecision(
                    action=PermissionAction.DENY, reason="denied", rule_source="test"
                )

        tool_delta = SimpleNamespace(
            index=0, id="call1",
            function=SimpleNamespace(name="write_file", arguments="{}"),
        )
        brain = FakeBrain([
            [_chunk(tool_calls=[tool_delta], usage=_usage())],
            [_chunk(content="replanned", usage=_usage())],
        ])

        dispatch = FakeDispatch()
        engine = IntentAwareEngine({})
        engine.dispatch = dispatch

        from agent.policy.policy_models import POLICY_DEFAULT
        archive = SessionArchive(db_path=str(tmp_path / "arc.db"))
        rt = ManagedAgentRuntime(
            session_engine=engine,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
            access_controller=DenyAll(policy=POLICY_DEFAULT),
            brain=brain,
            archive=archive,
        )

        denied_events: list[str] = []

        async def run():
            async for ev in rt.start_turn("do something risky", guard=RuntimeGuard(rt.runtime_config)):
                if ev.type == "tool_denied":
                    denied_events.append(ev.data.get("name", ""))

        asyncio.run(run())

        assert "write_file" in denied_events, (
            "Denied tool must emit tool_denied event; write_file was not denied"
        )


# ---------------------------------------------------------------------------
# T3.4 — trace_richness
# Spec: every run must emit all required trace fields.
# ---------------------------------------------------------------------------

class TestT34TraceRichness:

    def _run_and_collect_trace(self, tmp_path, *, tool_call: bool = False) -> Trace:
        """Run a turn via run_to_completion and return the populated Trace."""
        import uuid

        if tool_call:
            tool_delta = SimpleNamespace(
                index=0, id="call1",
                function=SimpleNamespace(name="read_file", arguments='{"path": "foo"}'),
            )
            brain = FakeBrain([
                [_chunk(tool_calls=[tool_delta], usage=_usage())],
                [_chunk(content="all done", usage=_usage())],
            ])
        else:
            brain = FakeBrain([[_chunk(content="all done", usage=_usage())]])

        archive = SessionArchive(db_path=str(tmp_path / "arc.db"))
        engine = IntentAwareEngine({})

        from agent.policy.policy_models import POLICY_DEFAULT
        from agent.policy.access_control import AccessController
        ac = AccessController(policy=POLICY_DEFAULT)

        rt = ManagedAgentRuntime(
            session_engine=engine,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=10, timeout_seconds=30),
            access_controller=ac,
            brain=brain,
            archive=archive,
        )
        trace = Trace(
            run_id=str(uuid.uuid4()),
            model="fake",
            scenario="t3_trace_richness",
            prompt="test input",
            context_strategy="truncate",
        )

        async def run():
            await rt.run_to_completion(
                user_input="test input",
                guard=RuntimeGuard(rt.runtime_config),
                trace=trace,
            )

        asyncio.run(run())
        return trace

    def test_trace_has_run_outcome(self, tmp_path) -> None:
        """Completed run must set trace.run_outcome or stop_reason."""
        trace = self._run_and_collect_trace(tmp_path)
        assert trace.stop_reason is not None or trace.run_outcome is not None, (
            "Trace must record stop_reason or run_outcome after a run"
        )

    def test_trace_records_token_usage(self, tmp_path) -> None:
        """Trace must accumulate token usage from LLM calls."""
        trace = self._run_and_collect_trace(tmp_path)
        usage = trace.total_usage
        assert usage.prompt_tokens > 0 or usage.total_tokens > 0, (
            "Trace must record token usage (got zeros)"
        )

    def test_trace_records_tool_calls(self, tmp_path) -> None:
        """When tools are called, trace.tool_calls must be populated."""
        trace = self._run_and_collect_trace(tmp_path, tool_call=True)
        assert len(trace.tool_calls) >= 1, (
            "Trace.tool_calls must be non-empty when the run included tool calls"
        )
        call = trace.tool_calls[0]
        assert "name" in call, "tool_call entry must have 'name'"
        assert "success" in call, "tool_call entry must have 'success'"
        assert "duration_ms" in call, "tool_call entry must have 'duration_ms'"

    def test_trace_has_all_required_top_level_fields(self, tmp_path) -> None:
        """Trace object must have all fields required by eval-suite §Trace requirements."""
        trace = self._run_and_collect_trace(tmp_path, tool_call=True)

        required_attrs = [
            "stop_reason",
            "tool_calls",
            "approval_decisions",
            "retrieval_injections",
            "recovery_events",
            "total_usage",
        ]
        for attr in required_attrs:
            assert hasattr(trace, attr), f"Trace missing required field: {attr}"
            val = getattr(trace, attr)
            assert val is not None, f"Trace field '{attr}' must not be None"

    def test_trace_records_recovery_event_on_tool_failure(self, tmp_path) -> None:
        """A failed tool execution must produce a recovery_event in the trace."""
        import uuid

        tool_delta = SimpleNamespace(
            index=0, id="call1",
            function=SimpleNamespace(name="failing_tool", arguments="{}"),
        )
        brain = FakeBrain([
            [_chunk(tool_calls=[tool_delta], usage=_usage())],
            [_chunk(content="recovered", usage=_usage())],
        ])

        archive = SessionArchive(db_path=str(tmp_path / "arc.db"))
        engine = IntentAwareEngine({})

        trace = Trace(
            run_id=str(uuid.uuid4()),
            model="fake",
            scenario="t3_recovery",
            prompt="trigger recovery",
            context_strategy="truncate",
        )

        from agent.policy.policy_models import POLICY_DEFAULT
        from agent.policy.access_control import AccessController
        ac = AccessController(policy=POLICY_DEFAULT)

        rt = ManagedAgentRuntime(
            session_engine=engine,
            model="fake",
            runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
            access_controller=ac,
            brain=brain,
            archive=archive,
        )

        async def run():
            await rt.run_to_completion(
                user_input="trigger recovery",
                guard=RuntimeGuard(rt.runtime_config),
                trace=trace,
            )

        asyncio.run(run())

        # "failing_tool" is unknown in FakeDispatch → unknown_tool recovery event
        assert len(trace.recovery_events) >= 1, (
            "Unknown tool call must produce a recovery_event in the trace"
        )
        kinds = [ev["kind"] for ev in trace.recovery_events]
        assert "unknown_tool" in kinds, (
            f"Expected 'unknown_tool' recovery event, got: {kinds}"
        )
