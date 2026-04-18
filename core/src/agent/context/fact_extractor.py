"""Fact extractor — pull key facts from conversation for pinning.

Extracts specific, reusable facts from messages that are about to be
evicted from the context window. These facts get pinned in Zone 1
so the agent doesn't lose critical information.

Examples of pinnable facts:
  - "AAPL RSI(14) = 34.2 (oversold) as of 2024-03-25"
  - "User's risk tolerance: moderate"
  - "Strategy 'momentum_v1' Sharpe ratio: 1.42"
"""

from __future__ import annotations

from typing import Any

import litellm

from config import settings


EXTRACT_PROMPT = """\
Extract key facts from the following conversation that should be remembered.
Focus on: specific numbers, data points, user preferences, tool results, and decisions.

Return ONLY a bullet-point list of facts, one per line. Start each with "- ".
If there are no key facts worth remembering, return "NONE".

Be specific — include numbers, dates, and symbols. Example:
- AAPL current price: $198.50 (as of 2024-03-25)
- User prefers momentum strategies over mean reversion
- RSI(14) for TSLA: 72.3 (overbought)

Conversation:
"""


async def extract_facts(
    messages: list[dict[str, Any]],
    compressor_model: str | None = None,
) -> list[str]:
    """Extract key facts from messages for pinning.

    Args:
        messages: Messages to extract facts from.
        compressor_model: LLM model for extraction.

    Returns:
        List of fact strings to pin in the context window.
    """
    model = compressor_model or settings.compressor_model

    # Build text from messages
    text_parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "tool":
            name = msg.get("name", "tool")
            if len(content) > 300:
                content = content[:300] + "..."
            text_parts.append(f"[Tool: {name}] {content}")
        elif role == "assistant" and content:
            text_parts.append(f"[Assistant] {content[:500]}")
        elif role == "user":
            text_parts.append(f"[User] {content}")

    if not text_parts:
        return []

    conversation_text = "\n".join(text_parts)

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            max_tokens=300,
        )
        result = response.choices[0].message.content.strip()

        if result.upper() == "NONE":
            return []

        # Parse bullet points
        facts = []
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                facts.append(line[2:].strip())
            elif line.startswith("* "):
                facts.append(line[2:].strip())

        return facts

    except Exception:
        return []
