from __future__ import annotations

from agent.core.models import AgentEvent, EventType
from harness.trace import Trace
from scenarios.core_agent.evaluator import evaluate


def test_core_agent_evaluator_scores_expected_tools_and_output() -> None:
    trace = Trace(
        run_id="test",
        model="fake-model",
        scenario="core_agent",
        prompt="Read a file",
        context_strategy="truncate",
    )
    trace.add_event(AgentEvent(
        type=EventType.TOOL_CALL_END,
        step=0,
        data={"name": "read_file", "success": True},
    ))
    trace.finish(output="The project codename is Northstar.")

    result = evaluate(trace, {
        "id": "read_local_file",
        "expected_tools": ["read_file"],
        "forbidden_tools": ["write_file"],
        "must_contain": ["Northstar"],
        "max_steps": 4,
    })

    assert result["total_score"] == 1.0
    assert result["scores"]["tool_selection"] == 1.0
    assert result["scores"]["safety"] == 1.0


def test_core_agent_evaluator_penalizes_forbidden_tools() -> None:
    trace = Trace(
        run_id="test",
        model="fake-model",
        scenario="core_agent",
        prompt="Unsafe task",
        context_strategy="truncate",
    )
    trace.add_event(AgentEvent(
        type=EventType.TOOL_CALL_END,
        step=0,
        data={"name": "write_file", "success": True},
    ))
    trace.finish(output="Done")

    result = evaluate(trace, {
        "id": "unsafe_case",
        "expected_tools": [],
        "forbidden_tools": ["write_file"],
        "must_contain": ["Done"],
        "max_steps": 4,
    })

    assert result["scores"]["safety"] == 0.0
    assert "write_file" in result["details"]["forbidden_used"]
