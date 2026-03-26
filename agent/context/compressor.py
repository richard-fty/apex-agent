"""Context compressor — summarize messages before discarding.

Uses a cheap/fast LLM (Haiku, GPT-4o-mini, DeepSeek) to summarize
rounds that are about to be dropped from the context window.
This preserves key information that would otherwise be lost.
"""

from __future__ import annotations

import json
from typing import Any

import litellm

from config import settings


COMPRESS_PROMPT = """\
Summarize the following conversation rounds into a brief, factual summary.
Focus on: key findings, data points, decisions made, and tool results.
Keep numbers and specific values. Be concise — 2-4 sentences max.

Conversation rounds to summarize:
"""


async def compress_messages(
    messages: list[dict[str, Any]],
    compressor_model: str | None = None,
) -> str:
    """Summarize a list of messages into a compact summary string.

    Args:
        messages: Messages to compress (typically oldest rounds being evicted).
        compressor_model: LLM model to use for summarization.

    Returns:
        A compact summary string.
    """
    model = compressor_model or settings.compressor_model

    # Build a text representation of the messages
    text_parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "tool":
            name = msg.get("name", "tool")
            # Truncate large tool results for the summarizer
            if len(content) > 500:
                content = content[:500] + "..."
            text_parts.append(f"[Tool: {name}] {content}")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                calls = ", ".join(
                    tc.get("function", {}).get("name", "?")
                    for tc in tool_calls
                )
                text_parts.append(f"[Assistant called: {calls}]")
            if content:
                text_parts.append(f"[Assistant] {content}")
        elif role == "user":
            text_parts.append(f"[User] {content}")

    if not text_parts:
        return ""

    conversation_text = "\n".join(text_parts)

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": COMPRESS_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            max_tokens=200,
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        # Fallback: crude truncation if LLM call fails
        return f"[Summary unavailable: {e}] " + conversation_text[:200]
