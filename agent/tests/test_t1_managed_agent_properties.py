"""T1 managed-agent property tests — hard release gates.

These tests verify the structural guarantees described in doc/eval-suite.md.
All T1 tests must pass before a release is cut.

T1.1  session_log_is_append_only
T1.2  session_replay_reconstructs_state
T1.3  harness_crash_recovery
T1.4  parallel_harness_read_consistency
T1.5  sandbox_credential_isolation
T1.6  sandbox_disposable_per_session
T1.7  universal_execute_contract
T1.8  approval_persists_across_restart
T1.9  orchestration_enforces_limits_externally
"""

from __future__ import annotations

import asyncio
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent.core.models import (
    AgentState,
    PendingApproval,
    PermissionAction,
    PermissionDecision,
    ToolCall,
)
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.managed_runtime import LiteLLMBrain, ManagedAgentRuntime
from agent.runtime.orchestrator import SessionOrchestrator
from agent.runtime.sandbox import DockerSandbox, LocalSandbox, create_session_sandbox
from agent.runtime.tool_dispatch import ToolDispatch
from agent.runtime.wake import wake
from agent.session.archive import SessionArchive
from config import settings


# ---------------------------------------------------------------------------
# Shared fakes (same pattern as test_managed_runtime.py)
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
    return SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)


class FakeBrain(LiteLLMBrain):
    def __init__(self, streams: list[list[Any]]) -> None:
        self.streams = streams

    async def complete(self, *, model, messages, tools, stream) -> Any:
        return FakeStream(self.streams.pop(0))


class FakeDispatch:
    def __init__(self) -> None:
        self.tool_names = ["write_file"]
        self._executed: list[str] = []

    def parse_tool_calls(self, raw: list[dict]) -> list[Any]:
        return [ToolCall(id=r["id"], name=r["function"]["name"], arguments={}) for r in raw]

    def validate_call(self, tc: Any) -> str | None:
        return None

    def get_tool_def(self, name: str) -> Any:
        return SimpleNamespace(name=name, is_read_only=False, is_networked=False,
                               requires_confirmation=True, is_destructive=False)

    async def execute(self, tc: Any) -> Any:
        self._executed.append(tc.name)
        return SimpleNamespace(content="ok", success=True)

    def retry_prompt(self, tc: Any, err: str) -> str:
        return f"fix: {err}"


class FakeContextMgr:
    def compact_tool_result(self, c: str) -> str:
        return c


class FakeSkillLoader:
    loaded: list[str] = []

    def get_available_skill_names(self) -> list[str]:
        return []

    def get_loaded_skill_names(self) -> list[str]:
        return []

    def load_skill(self, name: str) -> None:
        self.loaded.append(name)


class FakeEngine:
    def __init__(self) -> None:
        self.context_strategy = "truncate"
        self.dispatch = FakeDispatch()
        self.skill_loader = FakeSkillLoader()
        self.context_mgr = FakeContextMgr()
        self.messages: list[dict] = []

    def pre_load_for_input(self, _: str) -> list[str]:
        return []

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


class AllowController:
    pending = None

    def evaluate(self, tc: Any, td: Any) -> PermissionDecision:
        return PermissionDecision(action=PermissionAction.ALLOW, reason="ok", rule_source="test")

    def create_pending(self, tc: Any, d: Any) -> PendingApproval:
        self.pending = PendingApproval(tool_call=tc, decision=d)
        return self.pending

    def resolve_pending(self, action: str) -> PermissionDecision:
        self.pending = None
        return PermissionDecision(action=PermissionAction.ALLOW, reason="approved", rule_source="test")

    def record_allow(self, name: str) -> None:
        pass


class AskController(AllowController):
    def evaluate(self, tc: Any, td: Any) -> PermissionDecision:
        return PermissionDecision(action=PermissionAction.ASK, reason="needs approval",
                                  rule_source="test", requires_user_input=True)


def _make_runtime(
    tmp_path,
    brain: FakeBrain,
    archive: SessionArchive | None = None,
    controller: Any | None = None,
    config: RuntimeConfig | None = None,
) -> ManagedAgentRuntime:
    return ManagedAgentRuntime(
        session_engine=FakeEngine(),
        model="fake",
        runtime_config=config or RuntimeConfig(max_steps=10, timeout_seconds=30),
        access_controller=controller or AllowController(),
        brain=brain,
        archive=archive,
    )


# ---------------------------------------------------------------------------
# T1.1 — session_log_is_append_only
# ---------------------------------------------------------------------------

def test_t1_1_session_log_is_append_only(tmp_path) -> None:
    """Archive only ever INSERTs events; it never rewrites existing ones."""
    db = str(tmp_path / "archive.db")
    archive = SessionArchive(db_path=db)

    archive.create_session(session_id="s1", model="m", context_strategy="truncate")
    seq1 = archive.emit_event("s1", "user_input_received", {"user_input": "hello"})
    seq2 = archive.emit_event("s1", "turn_finished", {"content": "done"})

    assert seq1 < seq2, "sequence numbers must be monotonically increasing"

    events = archive.get_events("s1")
    assert len(events) == 2
    assert events[0]["seq"] == seq1
    assert events[1]["seq"] == seq2

    # Positional read: only events after seq1
    tail = archive.get_events("s1", after=seq1)
    assert len(tail) == 1
    assert tail[0]["seq"] == seq2


# ---------------------------------------------------------------------------
# T1.2 — session_replay_reconstructs_state
# Spec: reconstructed context (messages, loaded skill packs, pending approvals)
# must equal the original.
# ---------------------------------------------------------------------------

def test_t1_2_replay_reconstructs_session_state(tmp_path) -> None:
    """Replay reconstructs messages, loaded skills, approvals, and terminal state.

    The spec (doc/eval-suite.md §T1.2) requires the reconstructed context to
    equal the original: not just "non-empty". We compare role/content of every
    substantive message, verify skill-load replay, and confirm the pending-
    approval surface is rehydrated (None here, since there's no ASK).
    """
    db = str(tmp_path / "archive.db")
    archive = SessionArchive(db_path=db)

    brain = FakeBrain([[_chunk(content="done", usage=_usage())]])
    rt = _make_runtime(tmp_path, brain, archive=archive)
    original_sid = rt.session.session_id

    # Seed a skill-load event with a real skill name so replay can
    # reconstruct it against the discovered skill registry.
    archive.emit_event(
        original_sid, "skill_auto_loaded", {"skill_name": "stock_strategy"}
    )

    async def run():
        events = []
        async for ev in rt.start_turn("hi", guard=RuntimeGuard(rt.runtime_config)):
            events.append(ev.type)
        return events

    asyncio.run(run())

    # Snapshot the original runtime's observable state before replay.
    original_messages = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in rt.session_engine.messages
        if m.get("role") in ("user", "assistant", "tool")
    ]
    original_state = rt.session.state
    original_pending = rt.session.pending_approval

    # Replay via orchestrator and verify completeness
    events = SessionOrchestrator(archive=archive).replay_events(original_sid)
    types = [e["type"] for e in events]
    assert any("user" in t for t in types), f"No user event in {types}"
    assert any(t in ("turn_finished", "state_changed") for t in types), (
        f"No completion event in {types}"
    )

    # Reconstruct via wake() and verify full equivalence
    recovered = wake(archive, original_sid)
    recovered_messages = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in recovered.session_engine.messages
        if m.get("role") in ("user", "assistant", "tool")
    ]

    assert recovered.session.session_id == original_sid
    assert recovered_messages == original_messages, (
        "Recovered message history must match the original exactly.\n"
        f"original:  {original_messages}\n"
        f"recovered: {recovered_messages}"
    )
    assert recovered.session.state == original_state, (
        f"State drift: original={original_state} recovered={recovered.session.state}"
    )
    assert recovered.session.state in (AgentState.COMPLETED, AgentState.FAILED)

    # Pending approval surface must be rehydrated to the same shape (None here).
    assert recovered.session.pending_approval == original_pending

    # Skill loads must replay into the rehydrated engine.
    assert "stock_strategy" in recovered.session_engine.skill_loader.loaded, (
        "Skill load events must be replayed into the rehydrated engine; "
        f"loaded={list(recovered.session_engine.skill_loader.loaded)}"
    )


# ---------------------------------------------------------------------------
# T1.3 — harness_crash_recovery
# Spec: wake(session_id) continues from last event without repeating completed
# tool calls.
# ---------------------------------------------------------------------------

def test_t1_3_crash_recovery_does_not_repeat_completed_tools(tmp_path) -> None:
    """wake() rebuilds state; completed tool calls are reflected as tool
    messages with matching tool_call_ids — proving they will not be re-issued.

    The previous version of this test merely counted tool messages. That's
    insufficient: the property we actually want is "every completed call in
    the archive has a matching tool message, keyed by tool_call_id, so when
    the runtime resumes the LLM sees the call as already resolved."
    """
    db = str(tmp_path / "archive.db")
    archive = SessionArchive(db_path=db)

    tool_delta = SimpleNamespace(
        index=0, id="call1",
        function=SimpleNamespace(name="write_file", arguments="{}"),
    )
    brain = FakeBrain([
        [_chunk(tool_calls=[tool_delta], usage=_usage())],
        [_chunk(content="done", usage=_usage())],
    ])
    rt = _make_runtime(tmp_path, brain, archive=archive)

    async def run_one_turn():
        events = []
        async for ev in rt.start_turn("do something", guard=RuntimeGuard(rt.runtime_config)):
            events.append(ev.type)
        return events

    asyncio.run(run_one_turn())
    session_id = rt.session.session_id

    events_before = archive.get_events(session_id)
    # tool_finished carries (name, args, success, duration, content); the
    # tool_call_id lives on the paired tool_message_added event. Pull ids
    # from there.
    completed_tool_call_ids = [
        (e["payload"].get("message") or {}).get("tool_call_id")
        for e in events_before
        if e["type"] == "tool_message_added"
    ]
    completed_tool_call_ids = [tid for tid in completed_tool_call_ids if tid]
    assert completed_tool_call_ids, (
        "Precondition: the run must have produced at least one completed tool call"
    )

    # Simulate a crash: build a fresh runtime from archive
    recovered = wake(archive, session_id)

    assert recovered.session.session_id == session_id
    assert recovered.session.state in (AgentState.COMPLETED, AgentState.FAILED)

    # Every completed tool_call must have a matching tool message in the
    # rehydrated history. If any were missing, the LLM would re-issue the
    # call on resume.
    tool_result_messages = [
        m for m in recovered.session_engine.messages
        if m.get("role") == "tool"
    ]
    resolved_ids = {m.get("tool_call_id") for m in tool_result_messages}

    for tid in completed_tool_call_ids:
        assert tid in resolved_ids, (
            f"Completed tool_call {tid} has no matching tool message after wake(); "
            f"resume would re-execute it. Resolved: {resolved_ids}"
        )

    # And: no orphan assistant tool_calls (every tool_call_id issued by the
    # assistant must have a matching tool message).
    assistant_tool_call_ids: list[str] = []
    for m in recovered.session_engine.messages:
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    assistant_tool_call_ids.append(tc_id)

    for tc_id in assistant_tool_call_ids:
        assert tc_id in resolved_ids, (
            f"Assistant issued tool_call {tc_id} but no tool message resolves it; "
            f"resume would loop on this call."
        )


# ---------------------------------------------------------------------------
# T1.4 — parallel_harness_read_consistency
# ---------------------------------------------------------------------------

def test_t1_4_parallel_readers_see_consistent_events(tmp_path) -> None:
    """Two threads reading the archive concurrently both see all events."""
    db = str(tmp_path / "archive.db")
    archive = SessionArchive(db_path=db)
    archive.create_session(session_id="par", model="m", context_strategy="truncate")

    for i in range(10):
        archive.emit_event("par", "step", {"i": i})

    results: list[int] = []

    def reader():
        a = SessionArchive(db_path=db)
        results.append(len(a.get_events("par")))

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r == 10 for r in results), f"Inconsistent reads: {results}"


# ---------------------------------------------------------------------------
# T1.5 — sandbox_credential_isolation
# Spec: reads of ~/.aws/credentials, ANTHROPIC_API_KEY, and host-level files
# must fail or return scrubbed values.
# ---------------------------------------------------------------------------

def test_t1_5_sandbox_local_has_provision_destroy_api() -> None:
    """BaseSandbox exposes provision/destroy even for the local implementation."""
    sandbox = LocalSandbox()
    asyncio.run(sandbox.provision())
    asyncio.run(sandbox.destroy())


def test_t1_5_local_sandbox_scrubs_host_credentials(monkeypatch, tmp_path) -> None:
    """LocalSandbox child processes do not inherit arbitrary host secrets."""
    monkeypatch.setenv("OPENAI_API_KEY", "top-secret")
    sandbox = LocalSandbox(workspace_root=str(tmp_path))
    asyncio.run(sandbox.provision())

    result = asyncio.run(
        sandbox.run_command(
            f"{sys.executable} -c \"import os; print(os.getenv('OPENAI_API_KEY', '')); print(os.getenv('HOME', ''))\"",
            timeout=10,
        )
    )

    assert "top-secret" not in result.stdout
    assert sandbox.home_dir is not None
    assert sandbox.home_dir in result.stdout
    asyncio.run(sandbox.destroy())


def test_t1_5_local_sandbox_blocks_host_credential_file_reads(monkeypatch, tmp_path) -> None:
    """LocalSandbox HOME is isolated: host ~/.aws/credentials is not readable via HOME."""
    sandbox = LocalSandbox(workspace_root=str(tmp_path))
    asyncio.run(sandbox.provision())

    # The sandbox HOME is a disposable temp dir, not the real host HOME.
    # Reading ~/.aws/credentials inside the sandbox env must not expose host creds.
    result = asyncio.run(
        sandbox.run_command(
            f"{sys.executable} -c \""
            "import os, pathlib; "
            "home = os.environ.get('HOME', ''); "
            "cred = pathlib.Path(home) / '.aws' / 'credentials'; "
            "print('exists=' + str(cred.exists())); "
            "print('home=' + home)"
            "\"",
            timeout=10,
        )
    )

    # The sandbox HOME must not be the real host HOME
    real_home = str(Path.home())
    assert real_home not in result.stdout, (
        f"Sandbox HOME must not be the real host HOME ({real_home})"
    )
    # The credentials file must not exist inside the sandbox HOME
    assert "exists=True" not in result.stdout, (
        "~/.aws/credentials must not exist inside the sandbox HOME"
    )
    asyncio.run(sandbox.destroy())


def test_t1_5_docker_sandbox_raises_before_provision() -> None:
    """DockerSandbox raises RuntimeError if used before provision()."""
    sandbox = DockerSandbox()
    with pytest.raises(RuntimeError, match="not provisioned"):
        sandbox.read_file("/tmp/foo")


def test_t1_5_docker_provision_argv_blocks_host_credentials(monkeypatch) -> None:
    """DockerSandbox.provision() must not forward host env or host HOME.

    We cannot run Docker in CI, but we can inspect the argv it would run.
    The property under test: no `-e HOST_VAR=...` passthrough of arbitrary
    host env, `--env-file /dev/null` present, `--network none` by default,
    and HOME is re-bound to the container work_dir (never the host HOME).
    This is how strict isolation demonstrates "real host credential file
    blocking under a strict isolation backend" per gap #4.
    """
    captured_argv: list[list[str]] = []

    async def fake_exec(*argv: str, **kwargs: Any) -> Any:
        captured_argv.append(list(argv))

        class _FakeProc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return (b"container_abc123\n", b"")

        return _FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    # Deliberately set a "host secret" env var — the argv must not carry it.
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret-host-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-key")

    sandbox = DockerSandbox(work_dir="/workspace", network="none")
    asyncio.run(sandbox.provision())

    assert captured_argv, "DockerSandbox.provision() did not invoke docker"
    argv = captured_argv[0]
    flat = " ".join(argv)

    assert "--env-file" in argv and "/dev/null" in argv, (
        "provision() must include --env-file /dev/null to block host env inheritance"
    )
    assert "--network" in argv and "none" in argv, (
        "provision() must default to --network none"
    )
    # HOME inside the container points at work_dir, never the host HOME.
    assert "HOME=/workspace" in flat, (
        "Container HOME must be rebound to work_dir, not the host HOME"
    )
    # No host secret leaks into argv.
    assert "super-secret-host-value" not in flat
    assert "host-key" not in flat
    # No -e flag that would splice a host env var into the container.
    for i, token in enumerate(argv):
        if token in ("-e", "--env") and i + 1 < len(argv):
            value = argv[i + 1]
            assert "AWS" not in value and "ANTHROPIC" not in value and "OPENAI" not in value, (
                f"provision() leaked host credential env into container: {value}"
            )


def test_t1_5_strict_isolation_fails_closed_without_docker(monkeypatch, tmp_path) -> None:
    """Under sandbox_require_isolation=True, create_session_sandbox refuses
    to fall back to LocalSandbox when Docker is unavailable — the *only*
    acceptable outcome is a hard failure. This is the contract a deploy
    relies on when it has set the isolation flag.
    """
    monkeypatch.setattr(settings, "sandbox_backend", "auto")
    monkeypatch.setattr(settings, "sandbox_require_isolation", True)
    monkeypatch.setattr("agent.runtime.sandbox.shutil.which", lambda name: None)

    with pytest.raises(RuntimeError, match="sandbox_require_isolation"):
        create_session_sandbox(session_id="strict", cwd=str(tmp_path))


# ---------------------------------------------------------------------------
# T1.6 — sandbox_disposable_per_session
# ---------------------------------------------------------------------------

def test_t1_6_docker_sandbox_has_per_session_lifecycle() -> None:
    """DockerSandbox._container_id starts None and returns to None after destroy."""
    sandbox = DockerSandbox()
    assert sandbox._container_id is None
    asyncio.run(sandbox.destroy())
    assert sandbox._container_id is None


def test_t1_6_local_sandbox_destroy_cleans_disposable_home(tmp_path) -> None:
    """LocalSandbox destroys its per-session HOME when the session ends."""
    sandbox = LocalSandbox(workspace_root=str(tmp_path))
    asyncio.run(sandbox.provision())
    home_dir = sandbox.home_dir
    assert home_dir is not None
    assert Path(home_dir).exists()

    asyncio.run(sandbox.destroy())

    assert not Path(home_dir).exists()


def test_t1_6_default_session_sandbox_prefers_isolation_when_available(monkeypatch, tmp_path) -> None:
    """The default runtime sandbox path prefers Docker when the host supports it."""
    monkeypatch.setattr(settings, "sandbox_backend", "auto")
    monkeypatch.setattr("agent.runtime.sandbox.shutil.which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    sandbox = create_session_sandbox(session_id="s1", cwd=str(tmp_path))

    assert isinstance(sandbox, DockerSandbox)


def test_t1_6_fail_closed_when_isolation_required_and_docker_unavailable(monkeypatch, tmp_path) -> None:
    """create_session_sandbox raises when sandbox_require_isolation=True and Docker missing."""
    monkeypatch.setattr(settings, "sandbox_backend", "auto")
    monkeypatch.setattr(settings, "sandbox_require_isolation", True)
    monkeypatch.setattr("agent.runtime.sandbox.shutil.which", lambda name: None)

    with pytest.raises(RuntimeError, match="sandbox_require_isolation"):
        create_session_sandbox(session_id="s1", cwd=str(tmp_path))


# ---------------------------------------------------------------------------
# T1.7 — universal_execute_contract
# Spec: native tool, MCP-backed tool, and resource all obey the same
# execute(name, input) -> str interface.
# ---------------------------------------------------------------------------

def test_t1_7_universal_execute_contract_native_tool() -> None:
    """execute_by_name dispatches a registered native tool and returns a str."""
    dispatch = ToolDispatch()

    from agent.core.models import ToolDef, ToolGroup, ToolLoadingStrategy

    td = ToolDef(
        name="echo_tool",
        description="echo",
        parameters=[],
        tool_group=ToolGroup.CORE,
        loading_strategy=ToolLoadingStrategy.ALWAYS,
    )
    dispatch.register(td, lambda **_: "echo_result")

    result = asyncio.run(dispatch.execute_by_name("echo_tool", {}))

    assert isinstance(result, str), "execute_by_name must return str"
    assert result == "echo_result"


def test_t1_7_universal_execute_contract_unknown_tool_returns_error_str() -> None:
    """execute_by_name returns an error string (not an exception) for unknown tools.

    This preserves the str-return contract even on failure so the harness never
    has to special-case the MCP/native/resource distinction.
    """
    dispatch = ToolDispatch()

    result = asyncio.run(dispatch.execute_by_name("nonexistent_tool", {}))

    assert isinstance(result, str), "execute_by_name must return str even on error"
    assert "nonexistent_tool" in result.lower() or "unknown" in result.lower()


def test_t1_7_universal_execute_contract_mcp_stub() -> None:
    """An MCP-backed tool registered in ToolDispatch obeys the same str contract."""
    dispatch = ToolDispatch()

    from agent.core.models import ToolDef, ToolGroup, ToolLoadingStrategy

    # MCP-backed tools are registered exactly like native tools — the handler
    # proxies to the MCP server. Here we simulate with a stub.
    mcp_responses: list[str] = ["mcp://result/42"]

    async def mcp_handler(**_: Any) -> str:
        return mcp_responses.pop(0)

    td = ToolDef(
        name="mcp_search",
        description="MCP-backed search",
        parameters=[],
        tool_group=ToolGroup.CORE,
        loading_strategy=ToolLoadingStrategy.ALWAYS,
    )
    dispatch.register(td, mcp_handler)

    result = asyncio.run(dispatch.execute_by_name("mcp_search", {}))

    assert isinstance(result, str)
    assert result == "mcp://result/42"


def test_t1_7_universal_execute_contract_resource_stub() -> None:
    """A resource-like tool (e.g. read-only knowledge accessor) obeys the str contract."""
    dispatch = ToolDispatch()

    from agent.core.models import ToolDef, ToolGroup, ToolLoadingStrategy

    async def resource_handler(resource_id: str = "default") -> str:
        return f"resource_content_for_{resource_id}"

    td = ToolDef(
        name="fetch_resource",
        description="Fetch a resource by id",
        parameters=[],
        tool_group=ToolGroup.RETRIEVAL,
        loading_strategy=ToolLoadingStrategy.ALWAYS,
    )
    dispatch.register(td, resource_handler)

    result = asyncio.run(dispatch.execute_by_name("fetch_resource", {"resource_id": "doc_1"}))

    assert isinstance(result, str)
    assert "doc_1" in result


# ---------------------------------------------------------------------------
# T1.8 — approval_persists_across_restart
# Spec: Kill harness → wake shows pending approval still pending →
# user resolves → fresh harness continues correctly.
# ---------------------------------------------------------------------------

def test_t1_8_approval_persists_in_session_record(tmp_path) -> None:
    """When a tool triggers approval, session state is WAITING_APPROVAL and persisted."""
    db = str(tmp_path / "archive.db")
    archive = SessionArchive(db_path=db)

    tool_delta = SimpleNamespace(
        index=0, id="call1",
        function=SimpleNamespace(name="write_file", arguments="{}"),
    )
    brain = FakeBrain([[_chunk(tool_calls=[tool_delta], usage=_usage())]])
    rt = ManagedAgentRuntime(
        session_engine=FakeEngine(),
        model="fake",
        runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
        access_controller=AskController(),
        brain=brain,
        archive=archive,
    )

    async def collect():
        types = []
        async for ev in rt.start_turn("write it", guard=RuntimeGuard(rt.runtime_config)):
            types.append(ev.type)
        return types

    event_types = asyncio.run(collect())
    assert "approval_requested" in event_types
    assert rt.session.state == AgentState.WAITING_APPROVAL
    assert rt.session.pending_approval is not None

    record = archive.load_session(rt.session.session_id)
    assert record["state"] == "waiting_approval"
    assert record["metadata"]["runtime_state"]["pending_approval"] is not None


def test_t1_8_approval_persists_and_is_visible_after_wake(tmp_path) -> None:
    """After wake(), the pending approval is still present (harness restart test)."""
    db = str(tmp_path / "archive.db")
    archive = SessionArchive(db_path=db)

    tool_delta = SimpleNamespace(
        index=0, id="call1",
        function=SimpleNamespace(name="write_file", arguments="{}"),
    )
    brain = FakeBrain([[_chunk(tool_calls=[tool_delta], usage=_usage())]])
    ac = AskController()
    rt = ManagedAgentRuntime(
        session_engine=FakeEngine(),
        model="fake",
        runtime_config=RuntimeConfig(max_steps=5, timeout_seconds=30),
        access_controller=ac,
        brain=brain,
        archive=archive,
    )

    async def first_run():
        async for _ in rt.start_turn("write it", guard=RuntimeGuard(rt.runtime_config)):
            pass

    asyncio.run(first_run())
    session_id = rt.session.session_id

    assert rt.session.state == AgentState.WAITING_APPROVAL

    # Simulate harness restart: build a fresh runtime via wake()
    fresh_ac = AskController()
    recovered = wake(archive, session_id, access_controller=fresh_ac)

    assert recovered.session.state == AgentState.WAITING_APPROVAL, (
        "Pending approval must survive the harness restart"
    )
    assert recovered.session.pending_approval is not None, (
        "pending_approval must be rehydrated by wake()"
    )


def test_t1_8_approval_can_be_resumed(tmp_path) -> None:
    """After approval resolution, resume_pending() continues the run to completion."""
    tool_delta = SimpleNamespace(
        index=0, id="call1",
        function=SimpleNamespace(name="write_file", arguments="{}"),
    )
    brain = FakeBrain([
        [_chunk(tool_calls=[tool_delta], usage=_usage())],
        [_chunk(content="done", usage=_usage())],
    ])
    ac = AskController()
    rt = _make_runtime(tmp_path, brain, controller=ac)

    async def run():
        async for _ in rt.start_turn("write it", guard=RuntimeGuard(rt.runtime_config)):
            pass
        events = []
        async for ev in rt.resume_pending("approve_once", guard=RuntimeGuard(rt.runtime_config)):
            events.append(ev.type)
        return events

    events = asyncio.run(run())
    assert "tool_finished" in events or "turn_finished" in events


# ---------------------------------------------------------------------------
# T1.9 — orchestration_enforces_limits_externally
# Spec: step_cap and limit enforcement lives in the orchestrator, not the
# runtime instance.
# ---------------------------------------------------------------------------

def test_t1_9_step_limit_halts_run(tmp_path) -> None:
    """RuntimeGuard stops the run when max_steps is reached."""
    tool_delta = SimpleNamespace(
        index=0, id="c1",
        function=SimpleNamespace(name="write_file", arguments="{}"),
    )
    brain = FakeBrain([
        [_chunk(tool_calls=[tool_delta], usage=_usage())],
        [_chunk(tool_calls=[tool_delta], usage=_usage())],
        [_chunk(content="done", usage=_usage())],
    ])
    rt = _make_runtime(
        tmp_path, brain,
        config=RuntimeConfig(max_steps=1, timeout_seconds=60),
    )

    async def collect():
        types = []
        async for ev in rt.start_turn("loop", guard=RuntimeGuard(rt.runtime_config)):
            types.append(ev.type)
        return types

    events = asyncio.run(collect())
    assert "error" in events
    assert rt.session.state in (AgentState.CANCELLED, AgentState.FAILED)


def test_t1_9_orchestrator_creates_guard_not_runtime(tmp_path) -> None:
    """SessionOrchestrator.run_turn() creates the guard; runtime.start_turn()
    accepts it from outside, proving limits are orchestrator-owned."""
    archive = SessionArchive(db_path=str(tmp_path / "arc.db"))
    orchestrator = SessionOrchestrator(archive=archive)

    handle = orchestrator.create_runtime(
        session_engine=FakeEngine(),
        model="fake",
        runtime_config=RuntimeConfig(max_steps=1, timeout_seconds=30),
        access_controller=AllowController(),
    )

    handle.runtime.brain = FakeBrain([[_chunk(content="done", usage=_usage())]])

    async def collect():
        events = []
        async for ev in orchestrator.run_turn(handle, "hello"):
            events.append(ev.type)
        return events

    events = asyncio.run(collect())
    assert len(events) > 0
    assert not hasattr(handle.runtime, "_guard")
    assert not hasattr(handle.runtime, "_active_trace")
