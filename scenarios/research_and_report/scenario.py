"""Research-and-report scenario — full-system eval across difficulty tiers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.runtime.trace import Trace
from scenarios.base import Scenario
from scenarios.research_and_report.evaluator import evaluate


class ResearchAndReportScenario(Scenario):
    @property
    def name(self) -> str:
        return "research_and_report"

    def get_skill_names(self) -> list[str]:
        return []

    def get_test_cases(self) -> list[dict[str, Any]]:
        path = Path(__file__).with_name("test_cases.json")
        return json.loads(path.read_text())

    def evaluate(self, trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
        return evaluate(trace, test_case)
