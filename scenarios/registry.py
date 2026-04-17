"""Scenario registry for benchmark execution."""

from __future__ import annotations

from scenarios.base import Scenario
from scenarios.core_agent.scenario import CoreAgentScenario
from scenarios.research_and_report.scenario import ResearchAndReportScenario
from scenarios.stock_strategy.scenario import StockStrategyScenario


def get_scenario(name: str) -> Scenario:
    scenarios: dict[str, Scenario] = {
        "core_agent": CoreAgentScenario(),
        "research_and_report": ResearchAndReportScenario(),
        "stock_strategy": StockStrategyScenario(),
    }
    try:
        return scenarios[name]
    except KeyError as exc:
        raise ValueError(f"Unknown scenario: {name}. Available: {', '.join(sorted(scenarios))}") from exc


def list_scenarios() -> list[str]:
    return ["core_agent", "research_and_report", "stock_strategy"]
