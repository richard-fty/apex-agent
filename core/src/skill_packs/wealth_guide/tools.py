"""Wealth guide skill — typed educational planning tools."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from typing import Any

from agent.artifacts import ArtifactKind, ArtifactSpec
from agent.runtime.tool_context import (
    emit_artifact_created,
    emit_artifact_finalized,
    emit_artifact_replace,
    get_tool_context,
)


_HOME_PATTERN = re.compile(r"\bhome|house|down payment|mortgage\b", re.IGNORECASE)
_LIQUID_PATTERN = re.compile(r"\bliquid|safety|cash\b", re.IGNORECASE)


async def build_wealth_snapshot(
    income: float,
    cash: float,
    monthly_expenses: float = 0,
    retirement: float = 0,
    brokerage: float = 0,
    rsus: float = 0,
    home_equity: float = 0,
    debt: dict[str, Any] | None = None,
    goals: list[str] | None = None,
) -> str:
    snapshot = _build_snapshot_payload(
        income=income,
        cash=cash,
        monthly_expenses=monthly_expenses,
        retirement=retirement,
        brokerage=brokerage,
        rsus=rsus,
        home_equity=home_equity,
        debt=debt or {},
        goals=goals or [],
    )
    artifact_id = await _write_json_artifact(
        kind=ArtifactKind.WEALTH_SNAPSHOT,
        name="wealth-snapshot.json",
        description="Structured wealth snapshot",
        payload=snapshot,
    )
    return json.dumps(
        {
            "artifact_id": artifact_id,
            "situation": snapshot["situation"],
            "flags": snapshot["flags"],
            "net_worth": snapshot["net_worth"],
            "liquid_net_worth": snapshot["liquid_net_worth"],
            "emergency_months": snapshot["emergency_fund"]["months_covered"],
        },
        indent=2,
    )


async def compare_paths(snapshot_id: str, paths: list[str]) -> str:
    snapshot = await _load_snapshot(snapshot_id)
    if snapshot is None:
        return json.dumps({"error": f"Snapshot artifact not found: {snapshot_id}"})

    normalized_paths = _normalize_paths(paths, snapshot["flags"])
    comparison = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "situation": snapshot["situation"],
        "paths": [
            _path_card(path_name, snapshot)
            for path_name in normalized_paths
        ],
    }
    artifact_id = await _write_json_artifact(
        kind=ArtifactKind.PATH_COMPARISON,
        name="path-comparison.json",
        description="Side-by-side capital allocation paths",
        payload=comparison,
    )
    return json.dumps(
        {
            "artifact_id": artifact_id,
            "situation": comparison["situation"],
            "path_names": [item["name"] for item in comparison["paths"]],
        },
        indent=2,
    )


async def generate_action_checklist(snapshot_id: str, chosen_path: str) -> str:
    snapshot = await _load_snapshot(snapshot_id)
    if snapshot is None:
        return json.dumps({"error": f"Snapshot artifact not found: {snapshot_id}"})

    markdown = _build_checklist_markdown(snapshot, chosen_path)
    artifact_id = await _write_markdown_artifact(
        kind=ArtifactKind.ACTION_CHECKLIST,
        name="action-checklist.md",
        description=f"Four-week checklist for {chosen_path}",
        markdown=markdown,
    )
    return json.dumps(
        {
            "artifact_id": artifact_id,
            "chosen_path": chosen_path,
            "weeks": 4,
        },
        indent=2,
    )


def _build_snapshot_payload(
    *,
    income: float,
    cash: float,
    monthly_expenses: float,
    retirement: float,
    brokerage: float,
    rsus: float,
    home_equity: float,
    debt: dict[str, Any],
    goals: list[str],
) -> dict[str, Any]:
    debt_items = _normalize_debt(debt)
    total_debt = round(sum(item["amount"] for item in debt_items), 2)
    investable_assets = max(cash, 0) + max(retirement, 0) + max(brokerage, 0) + max(rsus, 0)
    net_worth = round(investable_assets + max(home_equity, 0) - total_debt, 2)
    liquid_net_worth = round(max(cash, 0) + max(brokerage, 0) - total_debt, 2)
    has_expense_detail = monthly_expenses and monthly_expenses > 0
    months_covered = round(max(cash, 0) / monthly_expenses, 1) if has_expense_detail else 0.0
    target_months = 6
    goal_text = " ".join(goals).lower()
    gross_assets = max(investable_assets + max(home_equity, 0), 1)
    rsu_ratio = rsus / gross_assets if gross_assets else 0.0
    cash_ratio = cash / max(investable_assets, 1)
    debt_ratio = total_debt / max(max(cash, 0) + max(brokerage, 0) + 1, 1)

    flags: list[str] = []
    if has_expense_detail and months_covered < target_months:
        flags.append("low_emergency_buffer")
    if any(item["rate"] >= 7 for item in debt_items) or any(
        "credit" in item["name"] for item in debt_items
    ):
        flags.append("high_interest_debt")
    if rsu_ratio >= 0.35:
        flags.append("concentration_risk")
    if cash_ratio >= 0.5 and months_covered >= 9:
        flags.append("cash_drag")
    if _HOME_PATTERN.search(goal_text):
        flags.append("housing_goal")
    if _LIQUID_PATTERN.search(goal_text):
        flags.append("liquid_priority")

    if "high_interest_debt" in flags and total_debt >= 10000:
        situation = "debt_burdened"
    elif "housing_goal" in flags:
        situation = "home_saving"
    elif "concentration_risk" in flags:
        situation = "rsu_concentrated"
    elif "cash_drag" in flags or (cash_ratio >= 0.55 and months_covered >= 9):
        situation = "cash_heavy"
    else:
        situation = "long_term_builder"

    return {
        "schema_version": 1,
        "income": round(income, 2),
        "monthly_expenses": round(monthly_expenses, 2),
        "net_worth": net_worth,
        "liquid_net_worth": liquid_net_worth,
        "allocation": {
            "cash": round(cash, 2),
            "retirement": round(retirement, 2),
            "brokerage": round(brokerage, 2),
            "rsus": round(rsus, 2),
            "home_equity": round(home_equity, 2),
            "debt_total": total_debt,
        },
        "emergency_fund": {
            "months_covered": months_covered,
            "target_months": target_months,
        },
        "goals": goals,
        "debt_breakdown": debt_items,
        "situation": situation,
        "flags": flags,
        "ratios": {
            "cash_ratio": round(cash_ratio, 3),
            "rsu_ratio": round(rsu_ratio, 3),
            "debt_ratio": round(debt_ratio, 3),
        },
    }


def _normalize_debt(debt: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, raw in debt.items():
        amount: float
        rate: float = 0.0
        if isinstance(raw, dict):
            amount = float(raw.get("amount", 0) or 0)
            rate = float(raw.get("rate", 0) or 0)
        else:
            amount = float(raw or 0)
        if amount <= 0:
            continue
        items.append(
            {
                "name": str(name).replace("_", " "),
                "amount": round(amount, 2),
                "rate": round(rate, 2),
            }
        )
    return items


async def _write_json_artifact(
    *,
    kind: ArtifactKind,
    name: str,
    description: str,
    payload: dict[str, Any],
) -> str | None:
    artifact_id = await emit_artifact_created(
        spec=ArtifactSpec(
            kind=kind,
            name=name,
            mime="application/json",
            description=description,
        )
    )
    if artifact_id:
        await emit_artifact_replace(artifact_id, json.dumps(payload, indent=2))
        await emit_artifact_finalized(artifact_id)
    return artifact_id


async def _write_markdown_artifact(
    *,
    kind: ArtifactKind,
    name: str,
    description: str,
    markdown: str,
) -> str | None:
    artifact_id = await emit_artifact_created(
        spec=ArtifactSpec(
            kind=kind,
            name=name,
            mime="text/markdown; charset=utf-8",
            description=description,
        )
    )
    if artifact_id:
        await emit_artifact_replace(artifact_id, markdown)
        await emit_artifact_finalized(artifact_id)
    return artifact_id


async def _load_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    ctx = get_tool_context()
    if ctx is None or ctx.artifact_store is None:
        return None
    try:
        raw = await ctx.artifact_store.read_all(ctx.session_id, snapshot_id)
    except FileNotFoundError:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _normalize_paths(paths: list[str], flags: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        name = str(raw).strip()
        if not name:
            continue
        canonical = _canonical_path_name(name)
        if canonical in seen:
            continue
        normalized.append(canonical)
        seen.add(canonical)
    if "high_interest_debt" in set(flags) and "debt-first" not in seen:
        normalized.insert(0, "debt-first")
        seen.add("debt-first")
    if "concentration_risk" in set(flags) and "diversify" not in seen:
        normalized.append("diversify")
        seen.add("diversify")
    return normalized[:4]


def _canonical_path_name(name: str) -> str:
    lowered = name.strip().lower()
    aliases = {
        "treasury": "T-bills",
        "tbills": "T-bills",
        "t bills": "T-bills",
        "hysa": "HYSA-only",
    }
    return aliases.get(lowered, name.strip())


def _path_card(path_name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    goals = snapshot.get("goals", [])
    months = snapshot["emergency_fund"]["months_covered"]
    concentration = snapshot["ratios"]["rsu_ratio"]
    high_interest = "high_interest_debt" in snapshot["flags"]
    housing_goal = "housing_goal" in snapshot["flags"]

    templates: dict[str, dict[str, Any]] = {
        "T-bills": {
            "headline": "Keep near-term capital stable and liquid.",
            "pros": [
                "Low volatility for money that may be needed soon",
                "Simple place to park a large cash balance",
                "Fits home-saving and safety-first goals",
            ],
            "cons": [
                "Lower long-term growth than diversified investing",
                "Can feel too conservative if the horizon is long",
                "Inflation can still erode purchasing power",
            ],
            "best_for": "Near-term goals and users who value liquidity.",
            "required_concepts": ["time horizon", "liquidity risk", "opportunity cost"],
        },
        "HYSA-only": {
            "headline": "Maximize simplicity and flexibility while staying in cash.",
            "pros": [
                "Easy to understand and maintain",
                "Keeps every dollar available",
                "Works when the user is still building confidence",
            ],
            "cons": [
                "Least growth-oriented path",
                "Can leave too much money idle",
                "Rates can change quickly",
            ],
            "best_for": "Very short horizons or safety-first users.",
            "required_concepts": ["liquidity risk", "cash drag", "rate sensitivity"],
        },
        "split": {
            "headline": "Divide capital between safety and long-term growth.",
            "pros": [
                "Balances flexibility with forward progress",
                "Reduces regret versus all-in choices",
                "Works well when goals are mixed",
            ],
            "cons": [
                "Not the maximum-return path",
                "Requires discipline about what stays safe vs invested",
                "Still needs a clear rebalance habit",
            ],
            "best_for": "Users with more than one valid priority right now.",
            "required_concepts": ["bucket strategy", "liquidity risk", "sequence risk"],
        },
        "index": {
            "headline": "Use a diversified long-term investing path.",
            "pros": [
                "Broad diversification",
                "Simple long-term framework",
                "Good fit for long horizons and steady contributions",
            ],
            "cons": [
                "Can be too volatile for near-term goals",
                "Feels uncomfortable during drawdowns",
                "Requires patience and consistency",
            ],
            "best_for": "Long-term builders with no acute liquidity need.",
            "required_concepts": ["volatility", "time horizon", "diversification"],
        },
        "mixed-stocks": {
            "headline": "Blend broad investing with a smaller active stock sleeve.",
            "pros": [
                "Keeps most of the portfolio disciplined",
                "Leaves room for learning and conviction",
                "Can satisfy curiosity without dominating the plan",
            ],
            "cons": [
                "Adds complexity and mistake risk",
                "Can drift into overconfidence",
                "Needs limits on concentration",
            ],
            "best_for": "Long-term users who still want a small active component.",
            "required_concepts": ["position sizing", "concentration risk", "behavioral discipline"],
        },
        "debt-first": {
            "headline": "Use excess cash to remove expensive guaranteed drag first.",
            "pros": [
                "Improves cash flow immediately",
                "Creates a predictable return by avoiding interest expense",
                "Reduces financial stress and fragility",
            ],
            "cons": [
                "Less money available for investing in the short run",
                "Can feel slow compared with market upside stories",
                "Requires distinguishing cheap debt from expensive debt",
            ],
            "best_for": "Users with high-interest debt or heavy debt burden.",
            "required_concepts": ["interest drag", "cash flow", "risk-free return"],
        },
        "diversify": {
            "headline": "Reduce single-company or single-asset concentration over time.",
            "pros": [
                "Lowers portfolio fragility",
                "Reduces correlation between job and investments",
                "Creates a more balanced wealth base",
            ],
            "cons": [
                "Can feel emotionally hard if the asset has performed well",
                "May involve taxes or vesting constraints",
                "Takes discipline to follow through gradually",
            ],
            "best_for": "Users with heavy employer-stock concentration.",
            "required_concepts": ["concentration risk", "correlation risk", "tax awareness"],
        },
        "hold-with-hedge": {
            "headline": "Keep some concentrated exposure while adding protection elsewhere.",
            "pros": [
                "Acknowledges conviction while lowering all-or-nothing pressure",
                "Can be easier to stick with than immediate full diversification",
                "Lets the user preserve optional upside",
            ],
            "cons": [
                "Still leaves concentration risk in place",
                "Can become an excuse to delay hard decisions",
                "More complex than a clean diversified path",
            ],
            "best_for": "Users not ready to exit concentrated positions quickly.",
            "required_concepts": ["concentration risk", "behavioral risk", "partial diversification"],
        },
    }
    card = dict(templates.get(path_name, templates["split"]))
    card["name"] = path_name

    if path_name == "T-bills" and housing_goal:
        card["best_for"] = "Near-term goals like a home purchase and capital that should stay stable."
    if path_name == "split" and months < 6:
        card["headline"] = "Rebuild safety while still keeping some long-term momentum."
    if path_name == "diversify" and concentration >= 0.5:
        card["headline"] = "Reduce a very high concentration before it defines the whole plan."
    if path_name == "debt-first" and not high_interest:
        card["cons"][0] = "The case is weaker if debt costs are low and manageable."

    return card


def _build_checklist_markdown(snapshot: dict[str, Any], chosen_path: str) -> str:
    path = _canonical_path_name(chosen_path)
    intro = {
        "T-bills": "Stabilize near-term capital and make your cash purpose explicit.",
        "HYSA-only": "Keep the plan simple and preserve flexibility while you build confidence.",
        "split": "Separate safety money from long-term money and define the split clearly.",
        "index": "Set up a repeatable long-term investing habit around broad diversification.",
        "mixed-stocks": "Limit active risk while keeping the core of the plan disciplined.",
        "debt-first": "Remove expensive debt first, then revisit longer-term investing.",
        "diversify": "Reduce concentration and lower the risk that one company dominates your future.",
        "hold-with-hedge": "Keep some upside exposure, but define clear limits and protections.",
    }.get(path, "Turn the chosen path into a clear next-step plan.")

    weeks = _checklist_weeks(path, snapshot)
    lines = [
        f"# {path} Action Checklist",
        "",
        intro,
        "",
        f"Situation: `{snapshot['situation']}`",
        f"Flags: {', '.join(snapshot['flags']) if snapshot['flags'] else 'none'}",
        "",
    ]
    for idx, (title, items) in enumerate(weeks, start=1):
        lines.append(f"## Week {idx} — {title}")
        lines.append("")
        for item in items:
            lines.append(f"- [ ] {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _checklist_weeks(path: str, snapshot: dict[str, Any]) -> list[tuple[str, list[str]]]:
    monthly_expenses = snapshot["monthly_expenses"]
    safety_target = math.ceil(monthly_expenses * 6 / 1000) * 1000 if monthly_expenses else 0

    common = [
        ("Clarify the decision", [
            "Write down the goal this money is serving and the time horizon.",
            "List the top two reasons this path fits better than the alternatives.",
            "Note what would make you revisit the decision in 30 days.",
        ]),
        ("Set guardrails", [
            "Decide what amount must remain liquid no matter what.",
            "Define one rule that prevents impulsive changes after headlines or market moves.",
            "Save a short note explaining the tradeoff you are accepting.",
        ]),
    ]

    path_specific: dict[str, list[tuple[str, list[str]]]] = {
        "T-bills": [
            ("Protect liquidity", [
                f"Set a cash safety target of about ${safety_target:,} if that matches six months of spending.",
                "Separate near-term goal cash from everyday checking balances.",
                "Document when the money may be needed and what not to do with it before then.",
            ]),
            ("Review rates and workflow", [
                "Compare a Treasury ladder with other low-risk cash equivalents at a high level.",
                "Pick one simple cadence for reviewing rates, not a daily habit.",
                "Write a one-sentence rule for when you would move part of this bucket into a growth path.",
            ]),
        ],
        "HYSA-only": [
            ("Keep it simple", [
                "Name the cash buckets clearly: emergency, near-term goal, discretionary.",
                "Turn off the urge to optimize every week by setting a monthly review cadence.",
                "Write down the exact condition that would justify moving beyond a cash-only plan.",
            ]),
            ("Reduce drift", [
                "Check that idle cash is still attached to a real goal, not indecision.",
                "List one concept you still need to understand before taking more risk.",
                "Schedule a date to compare this path with a split path again.",
            ]),
        ],
        "split": [
            ("Define the buckets", [
                "Choose a simple safe-growth split and write down why it fits your horizon.",
                "Separate near-term needs from long-term money in your notes.",
                "Set a rule for when new cash goes to the safe bucket versus the growth bucket.",
            ]),
            ("Automate the behavior", [
                "Create one recurring review to rebalance back to your chosen split.",
                "Write down what market drop would tempt you to change the plan and why you should pause first.",
                "List the three concepts you still need to understand better before increasing risk.",
            ]),
        ],
        "index": [
            ("Start disciplined exposure", [
                "Define how much capital is truly long-term before taking market risk.",
                "Write down why broad diversification fits your time horizon.",
                "Decide how often you will review performance so you do not over-monitor.",
            ]),
            ("Protect behavior", [
                "Set a contribution habit or review cadence that is easy to keep.",
                "Write a rule for what you will do if markets fall sharply.",
                "List one reason not to add stock-picking before the core plan is stable.",
            ]),
        ],
        "mixed-stocks": [
            ("Limit active risk", [
                "Cap the active stock sleeve as a percentage of total investable assets.",
                "Write down why each active holding exists and what would invalidate it.",
                "Keep the core of the plan in a diversified framework.",
            ]),
            ("Avoid drift", [
                "Review whether the active sleeve is becoming a concentration problem.",
                "Write a hard rule against chasing recent winners with new money.",
                "List which decisions belong in the core plan and which belong in the exploratory sleeve.",
            ]),
        ],
        "debt-first": [
            ("Prioritize expensive debt", [
                "List debts by interest rate and note which ones are clearly high-cost.",
                "Choose the debt you will attack first and define the payoff order.",
                "Write down what cash buffer you will keep while paying debt down.",
            ]),
            ("Reopen the investing question later", [
                "Pick the milestone that triggers a fresh allocation review after debt improves.",
                "Track how much monthly cash flow is freed once balances fall.",
                "List the investing path you will revisit once expensive debt is under control.",
            ]),
        ],
        "diversify": [
            ("Reduce concentration", [
                "Write down the current concentration and why it matters.",
                "Choose a staged plan for reducing exposure instead of reacting all at once.",
                "List the practical constraints: taxes, vesting, blackout windows, or psychology.",
            ]),
            ("Rebuild balance", [
                "Define what a more balanced allocation would look like at a high level.",
                "Write a rule that stops new money from increasing concentration further.",
                "Schedule a review date to compare the concentration again after action.",
            ]),
        ],
        "hold-with-hedge": [
            ("Define the limits", [
                "Write down the maximum concentration you are willing to tolerate.",
                "Specify what 'partial diversification' means in practice for you.",
                "List the exact reason you are keeping some concentrated exposure.",
            ]),
            ("Avoid indefinite drift", [
                "Set a deadline for revisiting whether this should become a full diversification plan.",
                "Document what evidence would make holding less reasonable over time.",
                "Define one action that lowers risk even if you keep exposure.",
            ]),
        ],
    }

    tail = path_specific.get(path, [])
    weeks = common[:1] + tail + common[1:]
    return weeks[:4]
