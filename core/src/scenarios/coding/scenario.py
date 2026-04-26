"""Coding ability regression scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.runtime.trace import Trace
from scenarios.base import Scenario


class CodingScenario(Scenario):
    @property
    def name(self) -> str:
        return "coding"

    def get_skill_names(self) -> list[str]:
        return ["coding"]

    def get_test_cases(self) -> list[dict[str, Any]]:
        cases_dir = Path(__file__).parent / "cases"
        cases = []
        for path in sorted(cases_dir.glob("case_*.json")):
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        return cases

    def evaluate(self, trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
        gates = trace.gate_results
        install_passed = bool(gates.get("install"))
        build_passed = bool(gates.get("build"))
        test_passed = bool(gates.get("test"))
        score = 0.0
        if install_passed:
            score = 0.4 * int(build_passed) + 0.6 * int(test_passed)

        return {
            "test_case_id": test_case["id"],
            "total_score": round(score, 3),
            "install_passed": install_passed,
            "build_passed": build_passed,
            "test_passed": test_passed,
            "steps": trace.step_count,
            "tokens": trace.total_usage.total_tokens,
            "cost_usd": trace.total_usage.cost_usd,
            "duration_seconds": trace.duration_seconds,
        }

