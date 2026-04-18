"""Token and cost tracking for the harness.

Consolidates what were previously ``token_tracker`` (LiteLLM response
extraction) and ``cost_tracker`` (budget enforcement) into a single module so
the harness tracking surface is in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.core.models import TokenUsage


# ---------------------------------------------------------------------------
# Token extraction from LiteLLM responses
# ---------------------------------------------------------------------------


def extract_usage(litellm_response: Any) -> TokenUsage:
    """Extract token usage from a LiteLLM response object.

    Works with both streaming and non-streaming responses.
    """
    usage = getattr(litellm_response, "usage", None)
    if usage is None:
        return TokenUsage()

    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or 0

    # Get cost from LiteLLM's built-in cost tracking
    cost = 0.0
    try:
        from litellm import completion_cost
        cost = completion_cost(completion_response=litellm_response)
    except Exception:
        pass

    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens or (prompt_tokens + completion_tokens),
        cost_usd=cost,
    )


# ---------------------------------------------------------------------------
# Cost tracking and budget enforcement
# ---------------------------------------------------------------------------

# Pricing per 1M tokens (input, output) in USD
# Updated as of early 2025 — adjust as prices change
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "anthropic/claude-sonnet-4-20250514": (3.0, 15.0),
    "anthropic/claude-haiku-4-5-20251001": (0.80, 4.0),
    "anthropic/claude-opus-4-0-20250514": (15.0, 75.0),
    # OpenAI
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    # Google
    "gemini/gemini-1.5-pro": (1.25, 5.0),
    "gemini/gemini-1.5-flash": (0.075, 0.30),
    # DeepSeek
    "deepseek/deepseek-chat": (0.14, 0.28),
    "deepseek/deepseek-reasoner": (0.55, 2.19),
}


def estimate_cost(model: str, usage: TokenUsage) -> float:
    """Estimate cost from token usage and model pricing.

    Falls back to LiteLLM's cost if available, otherwise uses our pricing table.
    """
    if usage.cost_usd > 0:
        return usage.cost_usd

    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return 0.0

    input_cost_per_token = pricing[0] / 1_000_000
    output_cost_per_token = pricing[1] / 1_000_000

    return (
        usage.prompt_tokens * input_cost_per_token
        + usage.completion_tokens * output_cost_per_token
    )


@dataclass
class StepCost:
    """Cost breakdown for a single step."""
    step: int
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    tool_name: str | None = None


@dataclass
class CostTracker:
    """Tracks costs across an entire agent run."""
    model: str
    budget_usd: float | None = None  # Optional spending limit
    steps: list[StepCost] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    def add_step(self, step: int, usage: TokenUsage, tool_name: str | None = None) -> None:
        """Record cost for one LLM call."""
        cost = estimate_cost(self.model, usage)
        self.steps.append(StepCost(
            step=step,
            model=self.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=cost,
            tool_name=tool_name,
        ))
        self.total_cost_usd += cost
        self.total_prompt_tokens += usage.prompt_tokens
        self.total_completion_tokens += usage.completion_tokens

    def check_budget(self) -> str | None:
        """Check if cost budget is exceeded. Returns error message or None."""
        if self.budget_usd is not None and self.total_cost_usd > self.budget_usd:
            return (
                f"Cost budget exceeded: ${self.total_cost_usd:.4f} > "
                f"${self.budget_usd:.4f} budget"
            )
        return None

    def summary(self) -> dict[str, Any]:
        """Return a summary of costs."""
        return {
            "model": self.model,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "num_llm_calls": len(self.steps),
            "avg_cost_per_step": round(self.total_cost_usd / max(1, len(self.steps)), 6),
            "budget_usd": self.budget_usd,
            "budget_remaining": (
                round(self.budget_usd - self.total_cost_usd, 6)
                if self.budget_usd else None
            ),
        }