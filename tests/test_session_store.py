from __future__ import annotations

from pathlib import Path

from agent.core.models import AgentState
from agent.session.store import SessionStore


def test_session_store_persists_state_and_events(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path))
    record = store.create(
        session_id="abc123",
        model="fake-model",
        context_strategy="truncate",
        initial_task="hello",
    )

    assert record["state"] == AgentState.IDLE.value

    store.update_state(
        "abc123",
        state=AgentState.PAUSED,
        stop_reason="approval needed",
        events=[{"type": "tool_finished", "payload": {"name": "read_file"}}],
    )

    loaded = store.load("abc123")
    assert loaded is not None
    assert loaded["state"] == AgentState.PAUSED.value
    assert loaded["stop_reason"] == "approval needed"
    assert loaded["events"][0]["type"] == "tool_finished"
