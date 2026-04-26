"""Wealth guide skill pack — metadata and tool registration."""

from __future__ import annotations

import re

from agent.core.models import ToolDef, ToolGroup, ToolParameter
from skill_packs.base import SkillPack, ToolHandler
from skill_packs.wealth_guide.tools import (
    build_wealth_snapshot,
    compare_paths,
    generate_action_checklist,
)


class WealthGuideSkill(SkillPack):
    @property
    def name(self) -> str:
        return "wealth_guide"

    @property
    def description(self) -> str:
        return "Mass-affluent wealth guidance — snapshots, path comparison, and action checklists"

    @property
    def keywords(self) -> list[str]:
        return [
            "finance",
            "financial",
            "money",
            "advice",
            "guidance",
            "wealth",
            "planning",
            "plan",
            "net worth",
            "personal finance",
            "savings",
            "saving",
            "invest",
            "investing",
            "allocation",
            "cash allocation",
            "cash",
            "liquid",
            "safety",
            "portfolio",
            "retirement",
            "401k",
            "ira",
            "brokerage",
            "rsu",
            "rsus",
            "employer stock",
            "treasury",
            "t-bill",
            "index fund",
            "down payment",
            "home",
            "mortgage",
            "student loan",
            "debt",
            "emergency fund",
            "financial coach",
            "financial plan",
        ]

    def matches_intent(self, user_input: str) -> float:
        base = super().matches_intent(user_input)
        text = user_input.lower()
        words = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text))

        direct_terms = {
            "finance",
            "financial",
            "money",
            "wealth",
            "retirement",
            "debt",
            "mortgage",
            "cash",
            "savings",
            "saving",
            "rsu",
            "rsus",
        }
        planning_terms = {
            "advice",
            "guidance",
            "help",
            "plan",
            "planning",
            "decide",
            "decision",
            "allocate",
            "allocation",
            "invest",
            "investing",
        }

        direct_hits = len(words & direct_terms)
        planning_hits = len(words & planning_terms)

        if "what to do with my money" in text:
            return max(base, 0.7)
        if "financial advice" in text or "finance help" in text:
            return max(base, 0.7)
        if "wealth planning" in text or "financial planning" in text:
            return max(base, 0.75)
        if direct_hits >= 2:
            return max(base, 0.65)
        if direct_hits >= 1 and planning_hits >= 1:
            return max(base, 0.55)
        if "cash" in words and ("invest" in words or "investing" in words):
            return max(base, 0.55)
        return base

    def get_tools(self) -> list[tuple[ToolDef, ToolHandler]]:
        return [
            (
                ToolDef(
                    name="build_wealth_snapshot",
                    description="Build a first-pass wealth snapshot from income, cash, and optional details.",
                    parameters=[
                        ToolParameter(name="income", type="number", description="Annual income in dollars"),
                        ToolParameter(name="cash", type="number", description="Liquid cash or savings in dollars"),
                        ToolParameter(name="monthly_expenses", type="number", description="Average monthly expenses in dollars", required=False, default=0),
                        ToolParameter(name="retirement", type="number", description="Retirement account balances", required=False, default=0),
                        ToolParameter(name="brokerage", type="number", description="Brokerage or taxable balances", required=False, default=0),
                        ToolParameter(name="rsus", type="number", description="Employer stock or vested RSUs", required=False, default=0),
                        ToolParameter(name="home_equity", type="number", description="Home equity", required=False, default=0),
                        ToolParameter(name="debt", type="object", description="Debt summary by category, optionally including rates", required=False, default={}),
                        ToolParameter(name="goals", type="array", description="List of current financial goals", required=False, default=[]),
                    ],
                    is_read_only=True,
                    is_concurrency_safe=True,
                    requires_confirmation=False,
                    mutates_state=False,
                    tool_group=ToolGroup.SKILL,
                    compliance_scope="education",
                ),
                build_wealth_snapshot,
            ),
            (
                ToolDef(
                    name="compare_paths",
                    description="Compare 3 reasonable capital-allocation paths for a wealth snapshot.",
                    parameters=[
                        ToolParameter(name="snapshot_id", type="string", description="Artifact id of a prior wealth snapshot"),
                        ToolParameter(name="paths", type="array", description="3 path names to compare"),
                    ],
                    is_read_only=True,
                    is_concurrency_safe=True,
                    requires_confirmation=False,
                    mutates_state=False,
                    tool_group=ToolGroup.SKILL,
                    compliance_scope="education",
                ),
                compare_paths,
            ),
            (
                ToolDef(
                    name="generate_action_checklist",
                    description="Generate a four-week checklist for the chosen path.",
                    parameters=[
                        ToolParameter(name="snapshot_id", type="string", description="Artifact id of a prior wealth snapshot"),
                        ToolParameter(name="chosen_path", type="string", description="The chosen path name"),
                    ],
                    is_read_only=True,
                    is_concurrency_safe=True,
                    requires_confirmation=False,
                    mutates_state=False,
                    tool_group=ToolGroup.SKILL,
                    compliance_scope="education",
                ),
                generate_action_checklist,
            ),
        ]
