"""Context window manager — orchestrates strategies to fit messages into budget.

Memory layout:
  Zone 1: Pinned (hard-capped) — system prompt + tool schemas + plan + pinned facts + user memory
  Zone 2: Compressed History (optional) — summary of evicted rounds
  Zone 3: Recent Rounds — sliding window, fills remaining budget

Budget allocation:
  Zone 1 cap: PINNED_CAP (default 4096 tokens)
  Zone 3 floor: total_budget - zone_1_actual - zone_2_actual
  Pinned facts use LRU eviction when Zone 1 cap is hit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.context.strategies import ContextStrategy, get_strategy
from agent.context.token_counter import (
    estimate_messages_tokens,
    estimate_tools_tokens,
)
from config import ModelConfig, get_model_config

logger = logging.getLogger(__name__)

PINNED_CAP = 4096       # hard cap for Zone 1 pinned content (tokens)
OUTPUT_RESERVE = 4096   # reserved for model's response


@dataclass
class PinnedFact:
    """A single pinned fact with metadata for LRU tracking."""
    text: str
    tags: list[str] = field(default_factory=list)
    source_seq: int | None = None    # event seq that produced this fact
    last_referenced_turn: int = 0    # for LRU: updated when the fact is "useful"
    turn_pinned: int = 0             # when the fact was created


class ContextManager:
    """Manages the context window for an agent run."""

    def __init__(self, strategy_name: str, model: str) -> None:
        self.strategy: ContextStrategy = get_strategy(strategy_name)
        self.model = model
        self.model_config: ModelConfig = get_model_config(model)
        self.pinned_facts: list[PinnedFact] = []
        self.pinned_facts_cap: int = 30  # max number of facts (within token budget)
        self.compressed_history: str | None = None
        self._current_turn: int = 0

        # Metrics
        self.compaction_count: int = 0
        self.total_tokens_saved: int = 0
        self.facts_evicted: int = 0

    def pin_fact(
        self,
        text: str,
        *,
        tags: list[str] | None = None,
        source_seq: int | None = None,
    ) -> PinnedFact | None:
        """Pin a fact in Zone 1. Returns evicted fact if LRU triggered, else None."""
        # Deduplicate: don't pin if a very similar fact already exists
        text_lower = text.lower()
        for existing in self.pinned_facts:
            if text_lower in existing.text.lower() or existing.text.lower() in text_lower:
                existing.last_referenced_turn = self._current_turn
                return None

        fact = PinnedFact(
            text=text,
            tags=tags or [],
            source_seq=source_seq,
            turn_pinned=self._current_turn,
            last_referenced_turn=self._current_turn,
        )
        self.pinned_facts.append(fact)

        evicted = None
        if len(self.pinned_facts) > self.pinned_facts_cap:
            evicted = self._evict_lru()
        return evicted

    def forget_fact(self, substring: str) -> str | None:
        """Remove a pinned fact by substring match. Returns the removed text or None."""
        substring_lower = substring.lower()
        for i, fact in enumerate(self.pinned_facts):
            if substring_lower in fact.text.lower():
                removed = self.pinned_facts.pop(i)
                return removed.text
        return None

    def get_pinned_text(self) -> str:
        """Render pinned facts for Zone 1 injection."""
        if not self.pinned_facts:
            return ""
        lines = [f"## Key Facts ({len(self.pinned_facts)}/{self.pinned_facts_cap} slots)"]
        for fact in self.pinned_facts:
            tag_str = f" [{', '.join(fact.tags)}]" if fact.tags else ""
            lines.append(f"- {fact.text}{tag_str}")
        return "\n".join(lines)

    def _evict_lru(self) -> PinnedFact | None:
        """Remove the least-recently-referenced fact."""
        if not self.pinned_facts:
            return None
        oldest = min(self.pinned_facts, key=lambda f: f.last_referenced_turn)
        self.pinned_facts.remove(oldest)
        self.facts_evicted += 1
        logger.debug("LRU evicted pinned fact: %s", oldest.text[:80])
        return oldest

    def compact_tool_result(self, content: str, max_chars: int = 3000) -> str:
        """Compact a large tool result to save context space."""
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

        self._current_turn += 1
        return fitted
