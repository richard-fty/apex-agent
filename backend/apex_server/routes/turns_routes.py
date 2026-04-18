"""Turn kickoff and approval resolution routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apex_server.deps import AppState, User, get_state, require_user
from apex_server.runner import get_or_build_runner
from apex_server.routes.session_support import (
    ApprovalIn,
    TurnIn,
    owned_session,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/{session_id}/turns", status_code=202)
async def post_turn(
    session_id: str,
    payload: TurnIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> dict[str, str]:
    sess = await owned_session(session_id, user, state)
    runner = get_or_build_runner(state, session_id, sess.model)
    assert runner.session_id == session_id
    runner.start_turn_background(payload.user_input)
    return {"status": "accepted", "session_id": session_id}


@router.post("/{session_id}/approvals", status_code=202)
async def post_approval(
    session_id: str,
    payload: ApprovalIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> dict[str, str]:
    await owned_session(session_id, user, state)
    runner = state.runners.get(session_id)
    if runner is None:
        raise HTTPException(status_code=409, detail="No active session runner")
    runner.resume_pending_background(payload.action)
    return {"status": "accepted"}
