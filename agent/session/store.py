"""Lightweight session persistence for managed agent runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.core.models import AgentState


class SessionStore:
    """Persist session lifecycle and event data as JSON files."""

    def __init__(self, base_dir: str = "results/sessions") -> None:
        self.base_path = Path(base_dir)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def session_path(self, session_id: str) -> Path:
        return self.base_path / f"{session_id}.json"

    def create(
        self,
        *,
        session_id: str,
        model: str,
        context_strategy: str,
        initial_task: str | None = None,
    ) -> dict[str, Any]:
        existing = self.load(session_id)
        if existing is not None:
            return existing

        record = {
            "session_id": session_id,
            "state": AgentState.IDLE.value,
            "model": model,
            "context_strategy": context_strategy,
            "initial_task": initial_task,
            "stop_reason": None,
            "pending_approval": None,
            "metadata": {},
            "events": [],
        }
        self.save(record)
        return record

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self.session_path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, record: dict[str, Any]) -> None:
        self.session_path(record["session_id"]).write_text(
            json.dumps(record, indent=2, default=str),
            encoding="utf-8",
        )

    def update_state(
        self,
        session_id: str,
        *,
        state: AgentState,
        stop_reason: str | None = None,
        pending_approval: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        record = self.load(session_id)
        if record is None:
            raise ValueError(f"Unknown session: {session_id}")
        record["state"] = state.value
        record["stop_reason"] = stop_reason
        record["pending_approval"] = pending_approval
        if metadata is not None:
            record["metadata"] = metadata
        if events is not None:
            record["events"] = events
        self.save(record)
