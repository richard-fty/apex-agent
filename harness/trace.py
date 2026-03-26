"""Execution trace — captures every event during an agent run.

The trace is the core data structure for the harness. It records every LLM call,
tool call, result, token usage, and timing. Used for:
- Real-time display in TUI
- Post-run analysis and metrics
- Model comparison
- Replay
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent.models import AgentEvent, EventType, TokenUsage


class TraceStep(BaseModel):
    """A single step in the agent trace."""
    step: int
    event_type: EventType
    timestamp: float = Field(default_factory=time.time)
    data: dict[str, Any] = Field(default_factory=dict)
    token_usage: TokenUsage | None = None
    duration_ms: float | None = None


class Trace(BaseModel):
    """Full execution trace for one agent run."""
    run_id: str
    model: str
    scenario: str
    prompt: str
    context_strategy: str
    start_time: float = Field(default_factory=time.time)
    end_time: float | None = None
    steps: list[TraceStep] = Field(default_factory=list)
    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    final_output: str | None = None
    success: bool = True
    error: str | None = None

    def add_event(self, event: AgentEvent) -> None:
        """Add an event to the trace."""
        step = TraceStep(
            step=event.step,
            event_type=event.type,
            timestamp=event.timestamp,
            data=event.data,
        )
        self.steps.append(step)

    def add_llm_usage(self, usage: TokenUsage) -> None:
        """Accumulate token usage from an LLM call."""
        self.total_usage.prompt_tokens += usage.prompt_tokens
        self.total_usage.completion_tokens += usage.completion_tokens
        self.total_usage.total_tokens += usage.total_tokens
        self.total_usage.cost_usd += usage.cost_usd

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def step_count(self) -> int:
        """Number of tool-call steps (not total events)."""
        return sum(
            1 for s in self.steps if s.event_type == EventType.TOOL_CALL_END
        )

    def finish(self, output: str | None = None, error: str | None = None) -> None:
        """Mark the trace as complete."""
        self.end_time = time.time()
        self.final_output = output
        if error:
            self.success = False
            self.error = error

    def save(self, directory: str = "results") -> Path:
        """Save trace to a JSON file."""
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        filename = f"{self.run_id}.json"
        filepath = path / filename
        filepath.write_text(json.dumps(self.model_dump(), indent=2, default=str))
        return filepath

    @classmethod
    def load(cls, filepath: str | Path) -> Trace:
        """Load a trace from a JSON file."""
        data = json.loads(Path(filepath).read_text())
        return cls.model_validate(data)
