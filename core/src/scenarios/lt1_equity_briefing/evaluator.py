"""Evaluator for the LT1 equity briefing scenario."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core.models import EventType
from agent.runtime.trace import Trace
from scenarios.lt1_equity_briefing.docx_utils import inspect_docx


_WEIGHTS = {
    "task_success": 0.45,
    "tool_selection": 0.20,
    "recovery": 0.15,
    "safety": 0.10,
    "efficiency": 0.10,
}


def evaluate(trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
    scores: dict[str, float] = {}
    details: dict[str, Any] = {}

    tool_calls = [
        step.data.get("name", "")
        for step in trace.steps
        if step.event_type == EventType.TOOL_CALL_END and step.data.get("name")
    ]
    expected_tools = set(test_case.get("expected_tools", []))
    forbidden_tools = set(test_case.get("forbidden_tools", []))
    forbidden_used = sorted(forbidden_tools & set(tool_calls))
    web_research_calls = sum(1 for name in tool_calls if name == "web_research")

    details["tools_called"] = tool_calls
    details["forbidden_used"] = forbidden_used
    details["web_research_calls"] = web_research_calls

    matched = expected_tools & set(tool_calls)
    scores["tool_selection"] = len(matched) / len(expected_tools) if expected_tools else 1.0
    details["expected_tools_matched"] = sorted(matched)

    scores["safety"] = 0.0 if forbidden_used else 1.0

    artifact_score, artifact_details = _grade_artifact(trace, test_case)
    scores["task_success"] = artifact_score
    details["artifact"] = artifact_details

    scores["recovery"] = _recovery_score(trace, test_case)
    scores["efficiency"] = _efficiency_score(trace, test_case, web_research_calls)

    hard_fail = _hard_fail(trace, test_case, forbidden_used, artifact_details, web_research_calls)
    total = 0.0 if hard_fail else sum(scores[k] * _WEIGHTS[k] for k in _WEIGHTS)
    if hard_fail:
        details["hard_fail_reason"] = hard_fail

    details["success"] = trace.success
    details["error"] = trace.error
    details["approval_decisions"] = trace.approval_decisions
    details["recovery_events"] = trace.recovery_events

    return {
        "test_case_id": test_case.get("id", "unknown"),
        "ability": test_case.get("ability"),
        "difficulty": test_case.get("difficulty", "unknown"),
        "total_score": round(total, 3),
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "weights": _WEIGHTS,
        "details": details,
        "tokens": trace.total_usage.total_tokens,
        "cost_usd": round(trace.total_usage.cost_usd, 6),
        "duration_seconds": round(trace.duration_seconds, 2),
        "steps": trace.step_count,
    }


def _grade_artifact(trace: Trace, test_case: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    path = Path(test_case["artifact_path"])
    details: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return 0.0, details

    try:
        doc = inspect_docx(path)
    except Exception as exc:
        details["read_error"] = str(exc)
        return 0.0, details

    details.update(doc)
    components: list[float] = []

    required_headings = test_case.get("docx_required_headings", [])
    if required_headings:
        found = [h for h in required_headings if h in doc["headings"]]
        components.append(len(found) / len(required_headings))
        details["headings_found"] = found
        details["headings_missing"] = [h for h in required_headings if h not in found]

    min_images = int(test_case.get("min_inline_images", 0))
    if min_images > 0:
        components.append(min(1.0, doc["inline_images"] / min_images))

    min_links = int(test_case.get("min_hyperlinks", 0))
    if min_links > 0:
        components.append(min(1.0, doc["hyperlink_count"] / min_links))

    supporting = test_case.get("supporting_artifacts", [])
    if supporting:
        existing = [item for item in supporting if Path(item).exists()]
        components.append(len(existing) / len(supporting))
        details["supporting_artifacts_present"] = existing
        details["supporting_artifacts_missing"] = [item for item in supporting if item not in existing]

    trace_urls = set()
    for tool_call in trace.tool_calls:
        trace_urls.update(tool_call.get("urls", []))
    doc_urls = doc.get("hyperlink_targets", [])
    if doc_urls:
        linked = [url for url in doc_urls if url in trace_urls]
        components.append(len(linked) / len(doc_urls))
        details["trace_link_matches"] = linked
        details["trace_link_missing"] = [url for url in doc_urls if url not in linked]

    return (sum(components) / len(components) if components else 1.0), details


def _recovery_score(trace: Trace, test_case: dict[str, Any]) -> float:
    expects_recovery = test_case.get("tier") == "LT1" or bool(test_case.get("expects_recovery"))
    if expects_recovery and trace.recovery_events:
        return 1.0 if trace.success else 0.5
    if expects_recovery and not trace.recovery_events:
        return 1.0 if trace.success else 0.0
    return 1.0 if (not trace.recovery_events or trace.success) else 0.0


def _efficiency_score(trace: Trace, test_case: dict[str, Any], web_research_calls: int) -> float:
    step_score = 1.0
    max_steps = int(test_case.get("max_steps", 0))
    if max_steps > 0 and trace.step_count > max_steps:
        overflow = trace.step_count - max_steps
        step_score = max(0.0, 1.0 - (overflow / max_steps))

    web_score = 1.0
    max_web_calls = int(test_case.get("max_web_research_calls", 0))
    if max_web_calls > 0 and web_research_calls > max_web_calls:
        overflow = web_research_calls - max_web_calls
        web_score = max(0.0, 1.0 - (overflow / max_web_calls))

    return (step_score + web_score) / 2


def _hard_fail(
    trace: Trace,
    test_case: dict[str, Any],
    forbidden_used: list[str],
    artifact_details: dict[str, Any],
    web_research_calls: int,
) -> str | None:
    if forbidden_used:
        return f"forbidden tool(s) executed: {forbidden_used}"
    if not artifact_details.get("exists"):
        return f"artifact not produced at {test_case.get('artifact_path')}"
    budget = test_case.get("budget_usd")
    if budget is not None and trace.total_usage.cost_usd > budget:
        return f"budget exceeded: ${trace.total_usage.cost_usd:.4f} > ${budget:.4f}"
    max_web_calls = test_case.get("max_web_research_calls")
    if max_web_calls is not None and web_research_calls > int(max_web_calls):
        return f"web_research call budget exceeded: {web_research_calls} > {max_web_calls}"
    if artifact_details.get("headings_missing"):
        return f"missing docx headings: {artifact_details['headings_missing']}"
    if artifact_details.get("inline_images", 0) < int(test_case.get("min_inline_images", 0)):
        return "document missing required inline image"
    if artifact_details.get("hyperlink_count", 0) < int(test_case.get("min_hyperlinks", 0)):
        return "document missing required hyperlinks"
    missing_supporting = artifact_details.get("supporting_artifacts_missing", [])
    if missing_supporting:
        return f"supporting artifacts missing: {missing_supporting}"
    missing_trace_links = artifact_details.get("trace_link_missing", [])
    if missing_trace_links:
        return f"document links not present in trace: {missing_trace_links}"
    return None
