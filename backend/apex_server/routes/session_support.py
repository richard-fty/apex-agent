"""Shared Pydantic models and ownership helpers for session-scoped routes.

Runner construction lives in ``apex_server.runner`` so route files only import
models and ownership checks here — no runtime internals leak into route definitions.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from apex_server.deps import AppState, User


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


async def owned_session(session_id: str, user: User, state: AppState) -> SessionOut:
    """Load a session if and only if it belongs to the current user."""
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


__all__ = [
    "ApprovalIn",
    "SessionCreateIn",
    "SessionOut",
    "TurnIn",
    "owned_session",
]
