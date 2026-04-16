"""Metrics — compute benchmark metrics from a trace.

Metrics:
  - Tool call accuracy (expected vs actual tools called)
  - Step efficiency (how many steps to complete)
  - Token efficiency (tokens consumed)
  - Cost efficiency (USD spent)
  - Latency (wall clock time)
  - Context efficiency (how much context was used vs budget)
  - Error rate (failed tool calls)
  - Skill load time (how quickly the agent loaded relevant skills)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.core.models import EventType
from harness.trace import Trace


@dataclass
class RunMetrics:
    """Computed metrics for a single agent run."""

    # Identity
    run_id: str
    model: str
    scenario: str
    context_strategy: str

    # Completion
    success: bool
    error: str | None

    # Efficiency
    total_steps: int
    total_llm_calls: int
    total_tool_calls: int

    # Tokens
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    # Cost
    cost_usd: float

    # Timing
    duration_seconds: float
    avg_llm_latency_ms: float
    avg_tool_latency_ms: float

    # Tool usage
    tools_called: dict[str, int]  # tool_name → call count
    failed_tool_calls: int
    error_rate: float  # failed / total

    # Skill usage
    skills_loaded: list[str]
    steps_before_first_skill: int  # How many steps before loading a skill

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "scenario": self.scenario,
            "context_strategy": self.context_strategy,
            "success": self.success,
            "error": self.error,
            "total_steps": self.total_steps,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "duration_seconds": round(self.duration_seconds, 2),
            "avg_llm_latency_ms": round(self.avg_llm_latency_ms, 1),
            "avg_tool_latency_ms": round(self.avg_tool_latency_ms, 1),
            "tools_called": self.tools_called,
            "failed_tool_calls": self.failed_tool_calls,
            "error_rate": round(self.error_rate, 3),
            "skills_loaded": self.skills_loaded,
            "steps_before_first_skill": self.steps_before_first_skill,
        }


def compute_metrics(trace: Trace) -> RunMetrics:
    """Compute all metrics from an execution trace."""

    # Count events by type
    llm_calls = [s for s in trace.steps if s.event_type == EventType.LLM_CALL_END]
    tool_calls = [s for s in trace.steps if s.event_type == EventType.TOOL_CALL_END]

    # Tool usage breakdown
    tools_called: dict[str, int] = {}
    failed_count = 0
    for tc in tool_calls:
        name = tc.data.get("name", "unknown")
        tools_called[name] = tools_called.get(name, 0) + 1
        if not tc.data.get("success", True):
            failed_count += 1

    total_tool_calls = len(tool_calls)
    error_rate = failed_count / max(1, total_tool_calls)

    # Latency
    llm_latencies = [s.data.get("duration_ms", 0) for s in llm_calls]
    tool_latencies = [s.data.get("duration_ms", 0) for s in tool_calls]
    avg_llm_latency = sum(llm_latencies) / max(1, len(llm_latencies))
    avg_tool_latency = sum(tool_latencies) / max(1, len(tool_latencies))

    # Skill loading
    skills_loaded = []
    steps_before_first_skill = -1
    for tc in tool_calls:
        if tc.data.get("name") == "load_skill":
            skill_name = tc.data.get("arguments", {}).get("name", "")
            if skill_name:
                skills_loaded.append(skill_name)
            if steps_before_first_skill == -1:
                steps_before_first_skill = tc.step

    if steps_before_first_skill == -1:
        steps_before_first_skill = trace.step_count  # Never loaded a skill

    return RunMetrics(
        run_id=trace.run_id,
        model=trace.model,
        scenario=trace.scenario,
        context_strategy=trace.context_strategy,
        success=trace.success,
        error=trace.error,
        total_steps=trace.step_count,
        total_llm_calls=len(llm_calls),
        total_tool_calls=total_tool_calls,
        prompt_tokens=trace.total_usage.prompt_tokens,
        completion_tokens=trace.total_usage.completion_tokens,
        total_tokens=trace.total_usage.total_tokens,
        cost_usd=trace.total_usage.cost_usd,
        duration_seconds=trace.duration_seconds,
        avg_llm_latency_ms=avg_llm_latency,
        avg_tool_latency_ms=avg_tool_latency,
        tools_called=tools_called,
        failed_tool_calls=failed_count,
        error_rate=error_rate,
        skills_loaded=skills_loaded,
        steps_before_first_skill=steps_before_first_skill,
    )
