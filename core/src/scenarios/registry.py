"""Scenario registry for benchmark execution."""

from __future__ import annotations

from scenarios.base import Scenario
from scenarios.core_agent.scenario import CoreAgentScenario
from scenarios.coding.scenario import CodingScenario
from scenarios.lt1_equity_briefing.scenario import LT1EquityBriefingScenario
from scenarios.research_and_report.scenario import ResearchAndReportScenario
from scenarios.stock_strategy.scenario import StockStrategyScenario
from scenarios.wealth_guide.scenario import WealthGuideScenario


def get_scenario(name: str) -> Scenario:
    scenarios: dict[str, Scenario] = {
        "core_agent": CoreAgentScenario(),
        "coding": CodingScenario(),
        "lt1_equity_briefing": LT1EquityBriefingScenario(),
        "research_and_report": ResearchAndReportScenario(),
        "stock_strategy": StockStrategyScenario(),
        "wealth_guide": WealthGuideScenario(),
    }
    try:
        return scenarios[name]
    except KeyError as exc:
        raise ValueError(f"Unknown scenario: {name}. Available: {', '.join(sorted(scenarios))}") from exc


def list_scenarios() -> list[str]:
    return ["coding", "core_agent", "lt1_equity_briefing", "research_and_report", "stock_strategy", "wealth_guide"]
