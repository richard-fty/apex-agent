"""LT1 equity research briefing scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.runtime.trace import Trace
from scenarios.base import Scenario
from scenarios.lt1_equity_briefing.evaluator import evaluate


class LT1EquityBriefingScenario(Scenario):
    @property
    def name(self) -> str:
        return "lt1_equity_briefing"

    def get_skill_names(self) -> list[str]:
        return ["stock_strategy"]

    def get_test_cases(self) -> list[dict[str, Any]]:
        path = Path(__file__).with_name("test_cases.json")
        return json.loads(path.read_text())

    def evaluate(self, trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
        return evaluate(trace, test_case)
