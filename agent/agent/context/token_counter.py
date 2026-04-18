"""Token estimation for context budget management.

Uses a simple heuristic (1 token ≈ 2 characters) for speed.
This is the same approach used by MOX and works well for mixed CJK/English text.
"""

from __future__ import annotations

import json
from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. ~1 token per 2 characters."""
    if not text:
        return 0
    return max(1, len(text) // 2)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single message dict (OpenAI format).

    Accounts for role, content, tool calls, and message overhead.
    """
    tokens = 4  # message overhead (role, separators)

    content = message.get("content")
    if content:
        tokens += estimate_tokens(content)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            func = tc.get("function", {})
            tokens += estimate_tokens(func.get("name", ""))
            tokens += estimate_tokens(func.get("arguments", ""))

    name = message.get("name")
    if name:
        tokens += estimate_tokens(name)

    return tokens


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages."""
    return sum(estimate_message_tokens(m) for m in messages)


def estimate_tools_tokens(tools: list[dict[str, Any]]) -> int:
    """Estimate tokens consumed by tool schemas in the request."""
    if not tools:
        return 0
    return estimate_tokens(json.dumps(tools))
