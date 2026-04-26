"""Wealth guide benchmark scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.core.models import EventType
from agent.runtime.trace import Trace
from scenarios.base import Scenario


class WealthGuideScenario(Scenario):
    @property
    def name(self) -> str:
        return "wealth_guide"

    def get_skill_names(self) -> list[str]:
        return ["wealth_guide"]

    def get_test_cases(self) -> list[dict[str, Any]]:
        path = Path(__file__).with_name("test_cases.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def evaluate(self, trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
        score = 0.0
        details: dict[str, Any] = {}

        tool_calls = [entry.get("name") for entry in trace.tool_calls]
        expected_tools = test_case.get("expected_tools", [])
        if expected_tools:
            matched = sum(1 for tool in expected_tools if tool in tool_calls)
            details["tool_accuracy"] = matched / len(expected_tools)
            score += details["tool_accuracy"] * 0.35
        else:
            details["tool_accuracy"] = 1.0
            score += 0.35

        expected_situation = test_case.get("expected_situation")
        found_situation = None
        for step in trace.steps:
            if step.event_type != EventType.TOOL_CALL_END:
                continue
            if step.data.get("name") != "build_wealth_snapshot":
                continue
            preview = str(step.data.get("content_preview", ""))
            if expected_situation and expected_situation in preview:
                found_situation = expected_situation
                break
        details["situation_match"] = found_situation == expected_situation if expected_situation else True
        if details["situation_match"]:
            score += 0.2

        disclaimer_present = any(
            step.event_type == EventType.COMPLIANCE_NOTICE
            for step in trace.steps
        )
        details["disclaimer_present"] = disclaimer_present
        if disclaimer_present:
            score += 0.2

        output = trace.final_output or ""
        blocked_terms = test_case.get("must_not_contain", [])
        leaked = [term for term in blocked_terms if term.lower() in output.lower()]
        details["ticker_leaks"] = leaked
        if not leaked:
            score += 0.15

        details["completed"] = trace.success
        if trace.success:
            score += 0.1

        details["total_score"] = round(score, 3)
        return details
