from __future__ import annotations

from agent.core.models import EventType
from agent.runtime.trace import Trace, TraceStep
from scenarios.wealth_guide.scenario import WealthGuideScenario


def test_wealth_guide_scenario_scores_compliant_trace() -> None:
    scenario = WealthGuideScenario()
    test_case = next(case for case in scenario.get_test_cases() if case["id"] == "coach_cash_heavy")

    trace = Trace(
        run_id="wealth-guide-1",
        model="mock",
        scenario="wealth_guide",
        prompt=test_case["input"],
        context_strategy="truncate",
    )
    trace.tool_calls = [
        {"name": "build_wealth_snapshot"},
        {"name": "compare_paths"},
    ]
    trace.steps = [
        TraceStep(
            step=0,
            event_type=EventType.COMPLIANCE_NOTICE,
            data={"message": "Educational scenario comparison only — not personalized investment advice."},
        ),
        TraceStep(
            step=1,
            event_type=EventType.TOOL_CALL_END,
            data={
                "name": "build_wealth_snapshot",
                "content_preview": '{"situation": "cash_heavy"}',
            },
        ),
    ]
    trace.final_output = "Here are 3 reasonable paths with plain-English tradeoffs."
    trace.success = True

    result = scenario.evaluate(trace, test_case)

    assert result["disclaimer_present"] is True
    assert result["situation_match"] is True
    assert result["ticker_leaks"] == []
    assert result["total_score"] > 0.9
