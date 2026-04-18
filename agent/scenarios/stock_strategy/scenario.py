"""Stock strategy benchmark scenario."""

from __future__ import annotations

from typing import Any

from agent.runtime.trace import Trace
from scenarios.base import Scenario
from agent.core.models import EventType


class StockStrategyScenario(Scenario):
    @property
    def name(self) -> str:
        return "stock_strategy"

    def get_skill_names(self) -> list[str]:
        return ["stock_strategy"]

    def get_test_cases(self) -> list[dict[str, Any]]:
        return [
            {
                "input": "Analyze AAPL stock",
                "expected_tools": ["fetch_market_data"],
                "must_contain": ["AAPL"],
            },
            {
                "input": "Compare BTC-USD and ETH-USD over 3 months",
                "expected_tools": ["fetch_market_data", "fetch_market_data"],
                "must_contain": ["BTC", "ETH"],
            },
            {
                "input": "Analyze INVALID_TICKER_XYZ",
                "expected_tools": ["fetch_market_data"],
                "expect_graceful_error": True,
            },
        ]

    def evaluate(self, trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
        """Grade the agent's performance."""
        score = 0.0
        details: dict[str, Any] = {}

        # Check if expected tools were called
        tool_calls = [
            s.data.get("name")
            for s in trace.steps
            if s.event_type == EventType.TOOL_CALL_END
        ]
        expected = test_case.get("expected_tools", [])
        if expected:
            matched = sum(1 for t in expected if t in tool_calls)
            details["tool_accuracy"] = matched / len(expected)
            score += details["tool_accuracy"] * 0.4

        # Check if output contains required content
        must_contain = test_case.get("must_contain", [])
        if must_contain and trace.final_output:
            found = sum(1 for term in must_contain if term.lower() in trace.final_output.lower())
            details["content_accuracy"] = found / len(must_contain)
            score += details["content_accuracy"] * 0.3

        # Check completion
        if trace.success:
            score += 0.3
            details["completed"] = True
        else:
            details["completed"] = False

        details["total_score"] = round(score, 3)
        details["steps"] = trace.step_count
        details["tokens"] = trace.total_usage.total_tokens
        details["cost_usd"] = trace.total_usage.cost_usd

        return details
