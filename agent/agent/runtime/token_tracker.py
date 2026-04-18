"""Token and cost tracking from LiteLLM responses.

LiteLLM returns actual token usage from the provider in every response.
This module accumulates those numbers across steps for the harness.
"""

from __future__ import annotations

from typing import Any

from agent.core.models import TokenUsage


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
