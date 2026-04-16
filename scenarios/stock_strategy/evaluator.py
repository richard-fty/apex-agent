"""Stock strategy scenario evaluator — grades agent performance on test cases."""

from __future__ import annotations

from typing import Any

from agent.core.models import EventType
from harness.trace import Trace


def evaluate(trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
    """Grade the agent's performance on a stock strategy test case.

    Scoring (0.0 to 1.0):
      - Tool accuracy (0.3): Did the agent call the expected tools?
      - Content accuracy (0.3): Does the output contain required terms?
      - Completion (0.2): Did the agent finish successfully?
      - Efficiency (0.2): Did it stay within step limits?

    Returns a detailed score breakdown.
    """
    scores: dict[str, float] = {}
    details: dict[str, Any] = {}

    # -- Tool accuracy (0.3) ------------------------------------------------
    tool_calls_made = []
    for step in trace.steps:
        if step.event_type == EventType.TOOL_CALL_END:
            name = step.data.get("name", "")
            if name:
                tool_calls_made.append(name)

    expected_tools = test_case.get("expected_tools", [])
    if expected_tools:
        # Check each expected tool was called at least once
        expected_set = set(expected_tools)
        called_set = set(tool_calls_made)
        matched = expected_set & called_set
        scores["tool_accuracy"] = len(matched) / len(expected_set)
        details["expected_tools"] = list(expected_set)
        details["tools_called"] = tool_calls_made
        details["tools_matched"] = list(matched)
        details["tools_missing"] = list(expected_set - called_set)
    else:
        scores["tool_accuracy"] = 1.0

    # -- Content accuracy (0.3) ---------------------------------------------
    must_contain = test_case.get("must_contain", [])
    if must_contain and trace.final_output:
        output_lower = trace.final_output.lower()
        found = [term for term in must_contain if term.lower() in output_lower]
        scores["content_accuracy"] = len(found) / len(must_contain)
        details["must_contain"] = must_contain
        details["content_found"] = found
        details["content_missing"] = [t for t in must_contain if t not in found]
    elif must_contain and not trace.final_output:
        scores["content_accuracy"] = 0.0
        details["content_note"] = "No output produced"
    else:
        scores["content_accuracy"] = 1.0

    # -- Graceful error handling -------------------------------------------
    if test_case.get("expect_graceful_error"):
        if trace.success and trace.final_output:
            # Agent handled the error gracefully (didn't crash, produced output)
            scores["content_accuracy"] = 1.0
            details["graceful_error"] = True
        elif not trace.success:
            scores["content_accuracy"] = 0.5
            details["graceful_error"] = False
            details["error"] = trace.error

    # -- Skill loading check -----------------------------------------------
    if test_case.get("must_not_load_skill"):
        loaded_skill = any(
            s.data.get("name") == "load_skill"
            for s in trace.steps if s.event_type == EventType.TOOL_CALL_END
        )
        if loaded_skill:
            scores["tool_accuracy"] *= 0.5  # Penalty for unnecessary skill load
            details["unnecessary_skill_load"] = True

    # -- Completion (0.2) ---------------------------------------------------
    if trace.success:
        scores["completion"] = 1.0
    elif trace.error and "Timeout" in trace.error:
        scores["completion"] = 0.5  # Partial credit for timeout
    else:
        scores["completion"] = 0.0
    details["success"] = trace.success
    details["error"] = trace.error

    # -- Efficiency (0.2) ---------------------------------------------------
    max_steps = test_case.get("max_steps", 20)
    actual_steps = trace.step_count
    if actual_steps <= max_steps:
        scores["efficiency"] = 1.0
    elif actual_steps <= max_steps * 1.5:
        scores["efficiency"] = 0.5
    else:
        scores["efficiency"] = 0.0
    details["steps"] = actual_steps
    details["max_steps"] = max_steps

    # -- Weighted total -----------------------------------------------------
    total = (
        scores.get("tool_accuracy", 0) * 0.3
        + scores.get("content_accuracy", 0) * 0.3
        + scores.get("completion", 0) * 0.2
        + scores.get("efficiency", 0) * 0.2
    )

    return {
        "test_case_id": test_case.get("id", "unknown"),
        "total_score": round(total, 3),
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "details": details,
        "tokens": trace.total_usage.total_tokens,
        "cost_usd": round(trace.total_usage.cost_usd, 6),
        "duration_seconds": round(trace.duration_seconds, 2),
        "steps": trace.step_count,
    }
