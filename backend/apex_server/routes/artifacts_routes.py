"""Artifact content routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from apex_server.deps import AppState, User, get_state, require_user
from apex_server.routes.session_support import owned_session


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/artifacts/{artifact_id}")
async def get_artifact(
    session_id: str,
    artifact_id: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> Response:
    await owned_session(session_id, user, state)
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
        "wealth_snapshot": "application/json",
        "path_comparison": "application/json",
        "action_checklist": "text/markdown; charset=utf-8",
        "code": "text/plain; charset=utf-8",
        "image": "image/png",
        "pdf": "application/pdf",
        "terminal_log": "text/plain; charset=utf-8",
        "plan": "application/json",
        "file": "application/octet-stream",
    }.get(kind, "application/octet-stream")
