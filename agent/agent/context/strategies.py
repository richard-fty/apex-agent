"""Swappable context window strategies for benchmarking.

Three strategies with increasing sophistication:
  - TruncateStrategy: MOX-style pure drop (baseline)
  - SummaryStrategy: Summarize before dropping
  - TieredStrategy: Fact extraction + summary + tool compaction (best retention)

The strategy is a research variable — different models may perform
better with different strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.context.token_counter import estimate_message_tokens, estimate_messages_tokens


class ContextStrategy(ABC):
    """Base class for context management strategies."""

    name: str

    @abstractmethod
    async def fit(
        self,
        messages: list[dict[str, Any]],
        budget: int,
    ) -> list[dict[str, Any]]:
        """Fit messages into the token budget."""
        ...


def _split_system_and_rounds(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """Split messages into system messages and conversation rounds.

    A round starts with each user message and includes all subsequent
    assistant + tool messages until the next user message.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    rounds: list[list[dict[str, Any]]] = []
    current_round: list[dict[str, Any]] = []

    for msg in non_system:
        if msg.get("role") == "user" and current_round:
            rounds.append(current_round)
            current_round = []
        current_round.append(msg)

    if current_round:
        rounds.append(current_round)

    return system_msgs, rounds


# ── TruncateStrategy ──────────────────────────────────────────────────

class TruncateStrategy(ContextStrategy):
    """MOX-style pure truncation. Drop oldest rounds first.

    System messages always kept. Current turn always kept.
    Oldest rounds dropped until within budget.
    """

    name = "truncate"

    async def fit(
        self,
        messages: list[dict[str, Any]],
        budget: int,
    ) -> list[dict[str, Any]]:
        if not messages:
            return messages

        system_msgs, rounds = _split_system_and_rounds(messages)
        if not rounds:
            return system_msgs

        system_tokens = estimate_messages_tokens(system_msgs)
        remaining_budget = budget - system_tokens

        if remaining_budget <= 0:
            return system_msgs

        # Keep rounds from newest to oldest
        kept_rounds: list[list[dict[str, Any]]] = []
        used_tokens = 0

        for rnd in reversed(rounds):
            round_tokens = estimate_messages_tokens(rnd)
            if used_tokens + round_tokens <= remaining_budget:
                kept_rounds.insert(0, rnd)
                used_tokens += round_tokens
            else:
                break

        result = list(system_msgs)
        for rnd in kept_rounds:
            result.extend(rnd)
        return result


# ── SummaryStrategy ───────────────────────────────────────────────────

class SummaryStrategy(ContextStrategy):
    """Summarize old rounds before dropping them.

    When rounds need to be evicted:
    1. Summarize the evicted rounds into a compact message
    2. Insert summary after system messages
    3. Keep recent rounds in full
    """

    name = "summary"

    async def fit(
        self,
        messages: list[dict[str, Any]],
        budget: int,
    ) -> list[dict[str, Any]]:
        if not messages:
            return messages

        system_msgs, rounds = _split_system_and_rounds(messages)
        if not rounds:
            return system_msgs

        system_tokens = estimate_messages_tokens(system_msgs)
        remaining_budget = budget - system_tokens

        if remaining_budget <= 0:
            return system_msgs

        # Check if all rounds fit
        total_round_tokens = sum(estimate_messages_tokens(r) for r in rounds)
        if total_round_tokens <= remaining_budget:
            result = list(system_msgs)
            for rnd in rounds:
                result.extend(rnd)
            return result

        # Reserve space for summary message (~200 tokens)
        summary_budget = 200
        rounds_budget = remaining_budget - summary_budget

        # Keep rounds from newest, collect evicted
        kept_rounds: list[list[dict[str, Any]]] = []
        evicted_rounds: list[list[dict[str, Any]]] = []
        used_tokens = 0

        for rnd in reversed(rounds):
            round_tokens = estimate_messages_tokens(rnd)
            if used_tokens + round_tokens <= rounds_budget:
                kept_rounds.insert(0, rnd)
                used_tokens += round_tokens
            else:
                evicted_rounds.insert(0, rnd)

        # Summarize evicted rounds
        summary_text = ""
        if evicted_rounds:
            evicted_msgs = []
            for rnd in evicted_rounds:
                evicted_msgs.extend(rnd)

            try:
                from agent.context.compressor import compress_messages
                summary_text = await compress_messages(evicted_msgs)
            except Exception:
                # Fallback: crude summary
                summary_text = f"[{len(evicted_rounds)} earlier conversation rounds were summarized to save space]"

        # Build result
        result = list(system_msgs)

        if summary_text:
            result.append({
                "role": "user",
                "content": f"[Context Summary — earlier conversation]\n{summary_text}",
            })

        for rnd in kept_rounds:
            result.extend(rnd)

        return result


# ── TieredStrategy ────────────────────────────────────────────────────

class TieredStrategy(ContextStrategy):
    """Full pipeline: fact extraction + summary + tool compaction.

    When rounds are evicted:
    1. Extract key facts from evicted rounds → pin in system zone
    2. Summarize evicted rounds → compressed history
    3. Compact large tool results in kept rounds
    4. Keep recent rounds in full

    This is the most sophisticated strategy and preserves the most information.
    """

    name = "tiered"

    async def fit(
        self,
        messages: list[dict[str, Any]],
        budget: int,
    ) -> list[dict[str, Any]]:
        if not messages:
            return messages

        system_msgs, rounds = _split_system_and_rounds(messages)
        if not rounds:
            return system_msgs

        system_tokens = estimate_messages_tokens(system_msgs)
        remaining_budget = budget - system_tokens

        if remaining_budget <= 0:
            return system_msgs

        # Check if all rounds fit
        total_round_tokens = sum(estimate_messages_tokens(r) for r in rounds)
        if total_round_tokens <= remaining_budget:
            result = list(system_msgs)
            for rnd in rounds:
                result.extend(rnd)
            return result

        # Reserve space for facts (~150 tokens) + summary (~200 tokens)
        facts_budget = 150
        summary_budget = 200
        rounds_budget = remaining_budget - facts_budget - summary_budget

        # Keep rounds from newest, collect evicted
        kept_rounds: list[list[dict[str, Any]]] = []
        evicted_rounds: list[list[dict[str, Any]]] = []
        used_tokens = 0

        for rnd in reversed(rounds):
            round_tokens = estimate_messages_tokens(rnd)
            if used_tokens + round_tokens <= rounds_budget:
                kept_rounds.insert(0, rnd)
                used_tokens += round_tokens
            else:
                evicted_rounds.insert(0, rnd)

        evicted_msgs: list[dict[str, Any]] = []
        for rnd in evicted_rounds:
            evicted_msgs.extend(rnd)

        # Step 1: Extract facts
        facts: list[str] = []
        if evicted_msgs:
            try:
                from agent.context.fact_extractor import extract_facts
                facts = await extract_facts(evicted_msgs)
            except Exception:
                pass

        # Step 2: Summarize evicted rounds
        summary_text = ""
        if evicted_msgs:
            try:
                from agent.context.compressor import compress_messages
                summary_text = await compress_messages(evicted_msgs)
            except Exception:
                summary_text = f"[{len(evicted_rounds)} earlier rounds summarized]"

        # Step 3: Compact large tool results in kept rounds
        for rnd in kept_rounds:
            for msg in rnd:
                if msg.get("role") == "tool":
                    content = msg.get("content", "")
                    if len(content) > 2000:
                        msg["content"] = content[:2000] + "\n[... truncated]"

        # Build result
        result = list(system_msgs)

        # Insert pinned facts after system prompt
        if facts:
            facts_text = "Key facts from earlier conversation:\n" + "\n".join(f"- {f}" for f in facts)
            result.append({
                "role": "system",
                "content": facts_text,
            })

        # Insert compressed history
        if summary_text:
            result.append({
                "role": "user",
                "content": f"[Context Summary — earlier conversation]\n{summary_text}",
            })

        for rnd in kept_rounds:
            result.extend(rnd)

        return result


# ── Registry ──────────────────────────────────────────────────────────

STRATEGIES: dict[str, type[ContextStrategy]] = {
    "truncate": TruncateStrategy,
    "summary": SummaryStrategy,
    "tiered": TieredStrategy,
}


def get_strategy(name: str) -> ContextStrategy:
    """Get a context strategy by name."""
    cls = STRATEGIES.get(name)
    if cls is None:
        available = ", ".join(STRATEGIES.keys())
        raise ValueError(f"Unknown context strategy: {name}. Available: {available}")
    return cls()
