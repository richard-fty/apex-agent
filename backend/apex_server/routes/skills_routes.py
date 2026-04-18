"""Skill management routes: list + load + unload per session.

Mirrors the agent's ``SkillLoader`` API (`core/src/agent/skills/loader.py`) over
HTTP so the web UI can show available/loaded skills and let the user toggle
them explicitly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from apex_server.deps import AppState, User, get_state, require_user
from apex_server.runner import get_or_build_runner
from apex_server.routes.session_support import owned_session


router = APIRouter(prefix="/sessions/{session_id}/skills", tags=["skills"])


class SkillOut(BaseModel):
    name: str
    description: str
    keywords: list[str]
    loaded: bool


class SkillListOut(BaseModel):
    skills: list[SkillOut]


@router.get("", response_model=SkillListOut)
async def list_skills(
    session_id: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> SkillListOut:
    sess = await owned_session(session_id, user, state)
    runner = get_or_build_runner(state, session_id, sess.model)
    loader = runner.runtime.session_engine.skill_loader
    # Ensure `available` is populated (idempotent).
    if not loader.available:
        loader.discover()
    loaded = set(loader.loaded.keys())
    skills = [
        SkillOut(
            name=s.name,
            description=s.description,
            keywords=list(s.keywords),
            loaded=s.name in loaded,
        )
        for s in loader.available.values()
    ]
    skills.sort(key=lambda x: x.name)
    return SkillListOut(skills=skills)


@router.post("/{skill_name}", response_model=SkillOut, status_code=200)
async def load_skill(
    session_id: str,
    skill_name: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> SkillOut:
    sess = await owned_session(session_id, user, state)
    runner = get_or_build_runner(state, session_id, sess.model)
    loader = runner.runtime.session_engine.skill_loader
    if not loader.available:
        loader.discover()
    if skill_name not in loader.available:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill_name not in loader.loaded:
        loader.load_skill(skill_name)
        # Rebuild system prompt so the SKILL.md addition takes effect.
        runner.runtime.session_engine.rebuild_system_prompt()
    skill = loader.available[skill_name]
    return SkillOut(
        name=skill.name,
        description=skill.description,
        keywords=list(skill.keywords),
        loaded=True,
    )


@router.delete("/{skill_name}", status_code=204)
async def unload_skill(
    session_id: str,
    skill_name: str,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
):
    sess = await owned_session(session_id, user, state)
    runner = get_or_build_runner(state, session_id, sess.model)
    loader = runner.runtime.session_engine.skill_loader
    if skill_name in loader.loaded:
        loader.unload_skill(skill_name)
        runner.runtime.session_engine.rebuild_system_prompt()
    return None
