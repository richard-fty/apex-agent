"""Context window manager — orchestrates strategies to fit messages into budget.

Adopts MOX's three-zone layout:
  Zone 1: System (pinned, never evicted) — system prompt + tool schemas + pinned facts
  Zone 2: Compressed History — summary of discarded rounds (added in Phase 2)
  Zone 3: Recent Rounds — full messages, newest-first

The manager calculates the available budget and delegates to the active strategy.
"""

from __future__ import annotations

from typing import Any

from agent.context.strategies import ContextStrategy, get_strategy
from agent.context.token_counter import (
    estimate_messages_tokens,
    estimate_tools_tokens,
)
from config import ModelConfig, get_model_config


class ContextManager:
    """Manages the context window for an agent run."""

    def __init__(self, strategy_name: str, model: str) -> None:
        self.strategy: ContextStrategy = get_strategy(strategy_name)
        self.model = model
        self.model_config: ModelConfig = get_model_config(model)
        self.pinned_facts: list[str] = []  # Phase 2: extracted key facts
        self.compressed_history: str | None = None  # Phase 2: summary of old rounds

        # Metrics
        self.compaction_count: int = 0
        self.total_tokens_saved: int = 0

    def compact_tool_result(self, content: str, max_chars: int = 3000) -> str:
        """Compact a large tool result to save context space.

        Truncates with a note if the result is too large.
        Phase 2 will add LLM-based summarization.
        """
        if len(content) <= max_chars:
            return content

        truncated = content[:max_chars]
        return f"{truncated}\n\n[... truncated, {len(content)} total chars]"

    async def prepare(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Prepare messages to fit within the context window budget.

        Args:
            messages: Current full message history.
            tools: Tool schemas (consume part of the budget).

        Returns:
            Messages that fit within the model's context window.
        """
        tool_tokens = estimate_tools_tokens(tools) if tools else 0
        budget = self.model_config.input_budget - tool_tokens

        tokens_before = estimate_messages_tokens(messages)

        fitted = await self.strategy.fit(messages, budget)

        tokens_after = estimate_messages_tokens(fitted)
        if tokens_after < tokens_before:
            self.compaction_count += 1
            self.total_tokens_saved += tokens_before - tokens_after

        return fitted
