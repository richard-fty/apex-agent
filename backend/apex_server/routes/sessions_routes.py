"""Session CRUD + turn kickoff + approval resolution + SSE events + artifacts.

Ownership model (plan §7.0): every agent session has an owner_user_id. All
endpoints below verify `agent_session.owner_user_id == current_user.id`; on
mismatch, we return 404 to avoid leaking the session's existence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent.artifacts import FilesystemArtifactStore
from agent.events import StreamEnd
from agent.events.schema import event_adapter
from agent.runtime.guards import RuntimeConfig
from agent.runtime.shared_runner import SharedTurnRunner
from apex_server.deps import AppState, User, get_state, require_user
from agent.session.store import SessionSpec

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SessionCreateIn(BaseModel):
    model: str = "deepseek/deepseek-chat"
    context_strategy: str = "truncate"


class SessionOut(BaseModel):
    id: str
    model: str
    context_strategy: str
    state: str
    created_at: float


class TurnIn(BaseModel):
    user_input: str = Field(min_length=1)


class ApprovalIn(BaseModel):
    action: str = Field(pattern="^(approve_once|approve_session|deny|deny_session)$")


# ---------------------------------------------------------------------------
# Helpers: load session with ownership, get/build runner
# ---------------------------------------------------------------------------


async def _owned_session(session_id: str, user: User, state: AppState) -> SessionOut:
    sess = await state.session_store.get(session_id)
    if sess is None or sess.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionOut(
        id=sess.id,
        model=sess.model,
        context_strategy=sess.context_strategy,
        state=sess.state,
        created_at=sess.created_at,
    )


def _get_or_build_runner(state: AppState, session_id: str, model: str) -> SharedTurnRunner:
    runner = state.runners.get(session_id)
    if runner is not None:
        return runner
    # Lazy-build: a runner per session. For Phase 3 this becomes a worker
    # lookup; for MVP all runners live in the same process.
    import os

    from agent.policy.access_control import AccessController
    from agent.policy.policy_models import get_policy
    from agent.session.engine import SessionEngine

    engine = SessionEngine(model=model, context_strategy="truncate")
    # Default to `auto` for a single-tenant MVP — auto-approves common tool
    # calls so the user isn't prompted for every file write. Override with
    # APEX_POLICY=default (ask on risky tools) or APEX_POLICY=readonly (no
    # writes) when you deploy to untrusted users.
    policy_name = os.environ.get("APEX_POLICY", "auto")
    access = AccessController(policy=get_policy(policy_name))
    runner = SharedTurnRunner(
        session_engine=engine,
        access_controller=access,
        cost_tracker=None,
        model=model,
        runtime_config=RuntimeConfig(),
        archive=state.archive,
        event_bus=state.event_bus,
        # Reuse the DB session_id so the runtime publishes to the same bus
        # channel that the SSE handler subscribes to.
        session_id=session_id,
    )
    # Wire the server's singleton artifact store into the runtime.
    runner.runtime.artifact_store = state.artifact_store
    state.runners[session_id] = runner
    state.runtimes[session_id] = runner.runtime
    return runner


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    payload: SessionCreateIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> SessionOut:
    spec = SessionSpec(
        model=payload.model,
        context_strategy=payload.context_strategy,
        owner_user_id=user.id,
    )
    session = await state.session_store.create(spec)
    return SessionOut(
        id=session.id,
        model=session.model,
        context_strategy=session.context_strategy,
        state=session.state,
        created_at=session.created_at,
    )


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> list[SessionOut]:
    sessions = await state.session_store.list_for_user(user.id)
    return [
        SessionOut(
            id=s.id,
            model=s.model,
            context_strategy=s.context_strategy,
            state=s.state,
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> SessionOut:
    return await _owned_session(session_id, user, state)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> Response:
    await _owned_session(session_id, user, state)
    await state.session_store.delete(session_id)
    # Release any runtime in memory for this session.
    state.runners.pop(session_id, None)
    state.runtimes.pop(session_id, None)
    await state.event_bus.close_session(session_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Turn + approval
# ---------------------------------------------------------------------------


@router.post("/{session_id}/turns", status_code=202)
async def post_turn(
    session_id: str,
    payload: TurnIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> dict[str, str]:
    sess = await _owned_session(session_id, user, state)
    runner = _get_or_build_runner(state, session_id, sess.model)
    assert runner.session_id == session_id  # runner + bus channel aligned
    runner.start_turn_background(payload.user_input)
    return {"status": "accepted", "session_id": session_id}


@router.post("/{session_id}/approvals", status_code=202)
async def post_approval(
    session_id: str,
    payload: ApprovalIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> dict[str, str]:
    await _owned_session(session_id, user, state)
    runner = state.runners.get(session_id)
    if runner is None:
        raise HTTPException(status_code=409, detail="No active session runner")
    runner.resume_pending_background(payload.action)
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# SSE events
# ---------------------------------------------------------------------------


@router.get("/{session_id}/events")
async def stream_events(
    session_id: str,
    request: Request,
    last_event_id: str | None = None,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> EventSourceResponse:
    """Server-Sent Events stream of runtime events for a session.

    Clients open this once per session and leave it open across turns.
    On reconnect, include `Last-Event-ID` (the seq of the last event seen)
    to replay any events we missed from the in-memory bus buffer.
    """
    await _owned_session(session_id, user, state)
    since_seq: int | None = None
    raw_last = last_event_id or request.headers.get("last-event-id")
    if raw_last:
        try:
            since_seq = int(raw_last)
        except ValueError:
            since_seq = None

    async def event_gen():
        async for ev in state.event_bus.subscribe(session_id, since_seq=since_seq):
            yield {
                "id": str(ev.seq),
                "event": ev.type,
                "data": ev.model_dump_json(),
            }
            if isinstance(ev, StreamEnd):
                # Keep the SSE connection open across turns — only close on
                # explicit client disconnect. We do not yield the default
                # close here.
                continue

    return EventSourceResponse(event_gen())


# ---------------------------------------------------------------------------
# Artifacts (GET content)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/artifacts/{artifact_id}")
async def get_artifact(
    session_id: str,
    artifact_id: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> Response:
    await _owned_session(session_id, user, state)
    try:
        data = await state.artifact_store.read_all(session_id, artifact_id)
        meta = await state.artifact_store.metadata(session_id, artifact_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = meta.spec.mime or _kind_to_mime(meta.spec.kind.value)
    return Response(content=data, media_type=media_type)


def _kind_to_mime(kind: str) -> str:
    return {
        "markdown": "text/markdown; charset=utf-8",
        "text": "text/plain; charset=utf-8",
        "json": "application/json",
        "code": "text/plain; charset=utf-8",
        "image": "image/png",
        "pdf": "application/pdf",
        "terminal_log": "text/plain; charset=utf-8",
        "plan": "application/json",
        "file": "application/octet-stream",
    }.get(kind, "application/octet-stream")
