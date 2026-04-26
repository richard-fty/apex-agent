from __future__ import annotations

import json

import pytest

from agent.artifacts import ArtifactKind, FilesystemArtifactStore
from agent.events import InMemoryEventBus
from agent.runtime.tool_context import ToolContext, tool_context_scope
from skill_packs.wealth_guide.skill import WealthGuideSkill
from skill_packs.wealth_guide.tools import (
    build_wealth_snapshot,
    compare_paths,
    generate_action_checklist,
)


def test_wealth_guide_registers_expected_tools() -> None:
    skill = WealthGuideSkill()

    tool_defs = [tool_def for tool_def, _ in skill.get_tools()]

    assert skill.matches_intent("Help me decide what to do with my cash and RSUs") >= 0.35
    assert {tool.name for tool in tool_defs} == {
        "build_wealth_snapshot",
        "compare_paths",
        "generate_action_checklist",
    }
    assert all(tool.compliance_scope == "education" for tool in tool_defs)


@pytest.mark.asyncio
async def test_snapshot_compare_and_checklist_emit_artifacts(tmp_path) -> None:
    store = FilesystemArtifactStore(root=tmp_path / "artifacts")
    bus = InMemoryEventBus()
    ctx = ToolContext(
        session_id="session-1",
        turn_id="turn-1",
        event_bus=bus,
        artifact_store=store,
    )

    with tool_context_scope(ctx):
        snapshot_result = json.loads(
            await build_wealth_snapshot(
                income=180000,
                cash=120000,
                monthly_expenses=7000,
                retirement=50000,
                brokerage=10000,
                rsus=8000,
                home_equity=0,
                debt={},
                goals=["Buy a home in 3 years", "Keep more cash liquid"],
            )
        )
        snapshot_id = snapshot_result["artifact_id"]
        snapshot_meta = await store.metadata("session-1", snapshot_id)
        snapshot_payload = json.loads(
            (await store.read_all("session-1", snapshot_id)).decode("utf-8")
        )

        comparison_result = json.loads(
            await compare_paths(snapshot_id=snapshot_id, paths=["T-bills", "split", "index"])
        )
        comparison_id = comparison_result["artifact_id"]
        comparison_payload = json.loads(
            (await store.read_all("session-1", comparison_id)).decode("utf-8")
        )

        checklist_result = json.loads(
            await generate_action_checklist(snapshot_id=snapshot_id, chosen_path="split")
        )
        checklist_id = checklist_result["artifact_id"]
        checklist_meta = await store.metadata("session-1", checklist_id)
        checklist_md = (await store.read_all("session-1", checklist_id)).decode("utf-8")

    assert snapshot_result["situation"] == "home_saving"
    assert "housing_goal" in snapshot_result["flags"]
    assert snapshot_meta.spec.kind == ArtifactKind.WEALTH_SNAPSHOT
    assert snapshot_payload["schema_version"] == 1
    assert snapshot_payload["emergency_fund"]["months_covered"] >= 17

    assert comparison_result["path_names"] == ["T-bills", "split", "index"]
    assert len(comparison_payload["paths"]) == 3
    assert all(len(path["pros"]) == 3 for path in comparison_payload["paths"])
    assert all(len(path["cons"]) == 3 for path in comparison_payload["paths"])

    assert checklist_meta.spec.kind == ArtifactKind.ACTION_CHECKLIST
    assert "# split Action Checklist" in checklist_md
    assert "- [ ]" in checklist_md


@pytest.mark.asyncio
async def test_snapshot_classifies_debt_and_concentration_cases(tmp_path) -> None:
    store = FilesystemArtifactStore(root=tmp_path / "artifacts")
    bus = InMemoryEventBus()
    ctx = ToolContext(
        session_id="session-2",
        turn_id="turn-2",
        event_bus=bus,
        artifact_store=store,
    )

    with tool_context_scope(ctx):
        debt_case = json.loads(
            await build_wealth_snapshot(
                income=140000,
                cash=25000,
                monthly_expenses=6000,
                retirement=30000,
                brokerage=5000,
                rsus=0,
                debt={"student_loans": {"amount": 50000, "rate": 8.0}},
                goals=["Build long-term wealth"],
            )
        )
        rsu_case = json.loads(
            await build_wealth_snapshot(
                income=230000,
                cash=60000,
                monthly_expenses=9000,
                retirement=50000,
                brokerage=20000,
                rsus=180000,
                debt={},
                goals=["Build long-term wealth"],
            )
        )

    assert debt_case["situation"] == "debt_burdened"
    assert "high_interest_debt" in debt_case["flags"]
    assert rsu_case["situation"] == "rsu_concentrated"
    assert "concentration_risk" in rsu_case["flags"]


@pytest.mark.asyncio
async def test_snapshot_does_not_block_on_missing_optional_details(tmp_path) -> None:
    store = FilesystemArtifactStore(root=tmp_path / "artifacts")
    bus = InMemoryEventBus()
    ctx = ToolContext(
        session_id="session-3",
        turn_id="turn-3",
        event_bus=bus,
        artifact_store=store,
    )

    with tool_context_scope(ctx):
        snapshot_result = json.loads(
            await build_wealth_snapshot(
                income=160000,
                cash=75000,
                goals=["Invest my idle cash"],
            )
        )

    assert snapshot_result["situation"] == "long_term_builder"
    assert "needs_expense_detail" not in snapshot_result["flags"]
    assert "low_emergency_buffer" not in snapshot_result["flags"]
