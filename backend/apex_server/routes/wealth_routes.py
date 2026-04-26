"""Wealth-guide profile and checklist routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from apex_server.deps import AppState, User, get_state, require_user


router = APIRouter(prefix="/wealth", tags=["wealth"])


class FinancialProfileIn(BaseModel):
    income: float = Field(ge=0)
    cash: float = Field(ge=0)
    monthly_expenses: float = Field(default=0, ge=0)
    retirement: float = Field(default=0, ge=0)
    brokerage: float = Field(default=0, ge=0)
    rsus: float = Field(default=0, ge=0)
    home_equity: float = Field(default=0, ge=0)
    student_loans: float = Field(default=0, ge=0)
    student_loan_rate: float = Field(default=0, ge=0)
    credit_card_debt: float = Field(default=0, ge=0)
    other_debt: float = Field(default=0, ge=0)
    goals: list[str] = Field(default_factory=list)
    home_purchase_horizon: str | None = None


class ChecklistToggleIn(BaseModel):
    artifact_id: str
    item_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    completed: bool


@router.post("/profile", status_code=204)
async def upsert_profile(
    payload: FinancialProfileIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> Response:
    state.wealth_store.upsert_profile(user.id, payload.model_dump())
    return Response(status_code=204)


@router.get("/profile", response_model=FinancialProfileIn)
async def get_profile(
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> FinancialProfileIn:
    profile = state.wealth_store.get_profile(user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return FinancialProfileIn.model_validate(profile)


@router.get("/checklist")
async def get_checklist(
    artifact_id: str | None = Query(default=None),
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": state.wealth_store.list_checklist_items(user.id, artifact_id=artifact_id)
    }


@router.post("/checklist/toggle", status_code=204)
async def toggle_checklist(
    payload: ChecklistToggleIn,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> Response:
    state.wealth_store.set_checklist_item(
        user_id=user.id,
        artifact_id=payload.artifact_id,
        item_index=payload.item_index,
        text=payload.text,
        completed=payload.completed,
    )
    return Response(status_code=204)
