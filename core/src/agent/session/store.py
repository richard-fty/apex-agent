"""Session metadata store — wraps the configured archive behind a typed protocol.

Adds typed `Session`/`SessionSpec` models while keeping runtime event
mirroring in the archive layer.

Event mirroring (runtime -> archive) still happens via the runtime's
_persist_session path; this store only manages the Session row lifecycle.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Protocol

from pydantic import BaseModel, Field

from agent.events.schema import AgentEvent, event_adapter
from agent.session.archive import SessionArchive


class SessionSpec(BaseModel):
    """Descriptor for creating a new session."""

    model: str
    context_strategy: str = "truncate"
    owner_user_id: str | None = None
    project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    """A session row."""

    id: str
    model: str
    context_strategy: str
    state: str
    stop_reason: str | None = None
    owner_user_id: str | None = None
    project_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionPatch(BaseModel):
    """Partial update."""

    state: str | None = None
    stop_reason: str | None = None
    metadata: dict[str, Any] | None = None


_OWNER_META_KEY = "__owner_user_id"


class SessionStore(Protocol):
    """Typed session metadata store."""

    async def create(self, spec: SessionSpec, *, session_id: str | None = None) -> Session:
        ...

    async def get(self, session_id: str) -> Session | None:
        ...

    async def update(self, session_id: str, patch: SessionPatch) -> Session:
        ...

    async def list_for_user(self, owner_user_id: str) -> list[Session]:
        ...

    async def delete(self, session_id: str) -> None:
        ...

    async def append_event(
        self, session_id: str, event_type: str, payload: dict[str, Any]
    ) -> int:
        """Append a raw event dict, returning the assigned seq."""
        ...

    async def list_events(
        self, session_id: str, *, since_seq: int = 0
    ) -> list[AgentEvent]:
        """Return typed events newer than `since_seq`.

        Events stored via the legacy archive path may not parse as typed
        `AgentEvent`s; those are silently skipped. Callers that need raw
        dicts should use SessionArchive.get_events directly.
        """
        ...


class PostgresSessionStore:
    """SessionStore backed by the configured session archive."""

    def __init__(self, archive: SessionArchive | None = None) -> None:
        self.archive = archive or SessionArchive()

    # ---- public API --------------------------------------------------------

    async def create(
        self,
        spec: SessionSpec,
        *,
        session_id: str | None = None,
    ) -> Session:
        sid = session_id or str(uuid.uuid4())
        self.archive.create_session(
            session_id=sid,
            model=spec.model,
            context_strategy=spec.context_strategy,
            project_id=spec.project_id,
            metadata=dict(spec.metadata),
            owner_user_id=spec.owner_user_id,
        )
        session = await self.get(sid)
        assert session is not None  # we just created it
        return session

    async def get(self, session_id: str) -> Session | None:
        row = self.archive.load_session(session_id)
        if row is None:
            return None
        return self._row_to_session(row)

    async def update(self, session_id: str, patch: SessionPatch) -> Session:
        existing = await self.get(session_id)
        if existing is None:
            raise KeyError(f"session {session_id} not found")
        new_state = patch.state if patch.state is not None else existing.state
        new_reason = (
            patch.stop_reason if patch.stop_reason is not None else existing.stop_reason
        )
        # Merge metadata; `owner_user_id` lives in its own column so runtime
        # metadata updates here can't stomp ownership.
        merged_meta: dict[str, Any] | None = None
        if patch.metadata is not None:
            merged_meta = dict(existing.metadata)
            merged_meta.update(patch.metadata)
        self.archive.update_session_state(
            session_id,
            new_state,
            stop_reason=new_reason,
            metadata=merged_meta,
        )
        updated = await self.get(session_id)
        assert updated is not None
        return updated

    async def list_for_user(self, owner_user_id: str) -> list[Session]:
        out: list[Session] = []
        for session_id in self.archive.list_session_ids_for_user(owner_user_id):
            s = await self.get(session_id)
            if s is not None:
                out.append(s)
        return out

    async def delete(self, session_id: str) -> None:
        self.archive.delete_session(session_id)

    async def append_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        return self.archive.emit_event(session_id, event_type, payload)

    async def list_events(
        self,
        session_id: str,
        *,
        since_seq: int = 0,
    ) -> list[AgentEvent]:
        raw = self.archive.get_events(session_id, after=since_seq)
        out: list[AgentEvent] = []
        for row in raw:
            blob = {
                "type": row["type"],
                "seq": row["seq"],
                "timestamp": row["timestamp"],
                "session_id": session_id,
                **row["payload"],
            }
            try:
                out.append(event_adapter.validate_python(blob))
            except Exception:
                # Legacy event shape — skip; callers that need raw can use
                # SessionArchive.get_events directly.
                continue
        return out

    # ---- internals ---------------------------------------------------------

    @staticmethod
    def _row_to_session(row: dict[str, Any]) -> Session:
        metadata = dict(row.get("metadata") or {})
        # Owner lives in its own column (migrated from metadata stash).
        owner_user_id = row.get("owner_user_id") or metadata.pop(_OWNER_META_KEY, None)
        return Session(
            id=row["session_id"],
            model=row["model"],
            context_strategy=row["context_strategy"],
            state=row.get("state", "idle"),
            stop_reason=row.get("stop_reason"),
            owner_user_id=owner_user_id,
            project_id=row.get("project_id"),
            created_at=row.get("created_at", time.time()),
            metadata=metadata,
        )
