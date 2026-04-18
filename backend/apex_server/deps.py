"""Shared FastAPI dependencies and state container."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, HTTPException, Request, status

from agent.artifacts import ArtifactStore, FilesystemArtifactStore
from agent.events import EventBus, InMemoryEventBus
from apex_server.auth import (
    SESSION_COOKIE,
    AuthStore,
    User,
    _dev_bypass_enabled,
    dev_bypass_user,
)
from agent.session.archive import SessionArchive
from agent.session.store import SessionStore, SqliteSessionStore


@dataclass
class AppState:
    """Application-scoped singletons held on `app.state`.

    All sessions on this process share: one SessionArchive (SQLite file),
    one event bus (in-memory), one artifact store (filesystem), one auth
    store. Phase 3 (the server-side split) would replace some of these
    with Redis / Postgres adapters without changing the API routes.
    """

    archive: SessionArchive
    session_store: SessionStore
    event_bus: EventBus
    artifact_store: ArtifactStore
    auth: AuthStore
    # Runtimes for currently live sessions, keyed by session_id.
    runtimes: dict[str, Any] = field(default_factory=dict)
    runners: dict[str, Any] = field(default_factory=dict)


# backend/apex_server/deps.py -> ../../ is the repo root (apex_agent/).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    """Resolve ``results/`` at the repo root regardless of the launcher's cwd.

    Override with ``APEX_DATA_DIR=/some/absolute/path`` when you want to put
    data somewhere else (e.g., a mounted volume in prod).
    """
    override = os.environ.get("APEX_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _REPO_ROOT / "results"


def build_default_app_state(
    *,
    db_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
) -> AppState:
    """Build singletons with ONE SQLite file holding all related tables
    (users, auth_sessions, sessions, events, events_fts*). Artifacts live
    on the filesystem under ``artifact_root`` — bytes belong on disk, not
    in rows.
    """
    data_dir = _default_data_dir()
    resolved_db = Path(db_path) if db_path is not None else data_dir / "apex.db"
    resolved_artifacts = (
        Path(artifact_root) if artifact_root is not None else data_dir / "artifacts"
    )
    archive = SessionArchive(db_path=str(resolved_db))
    return AppState(
        archive=archive,
        session_store=SqliteSessionStore(archive=archive),
        event_bus=InMemoryEventBus(),
        artifact_store=FilesystemArtifactStore(root=resolved_artifacts),
        auth=AuthStore(db_path=str(resolved_db)),
    )


def get_state(request: Request) -> AppState:
    return request.app.state.app_state  # type: ignore[no-any-return]


async def require_user(
    request: Request,
    apex_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    """Resolve the current user from the session cookie or 401."""
    state = get_state(request)
    if _dev_bypass_enabled():
        return dev_bypass_user(state.auth)
    if not apex_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user = state.auth.resolve_session(apex_session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    return user
