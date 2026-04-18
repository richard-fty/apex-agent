"""Session CRUD routes.

Ownership model (plan §7.0): every agent session has an owner_user_id. All
endpoints below verify `agent_session.owner_user_id == current_user.id`; on
mismatch, we return 404 to avoid leaking the session's existence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from apex_server.deps import AppState, User, get_state, require_user
from apex_server.routes.session_support import SessionCreateIn, SessionOut, owned_session
from agent.session.store import SessionSpec


router = APIRouter(prefix="/sessions", tags=["sessions"])


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
    return await owned_session(session_id, user, state)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> Response:
    await owned_session(session_id, user, state)
    await state.session_store.delete(session_id)
    # Release any runtime in memory for this session.
    state.runners.pop(session_id, None)
    state.runtimes.pop(session_id, None)
    await state.event_bus.close_session(session_id)
    return Response(status_code=204)
