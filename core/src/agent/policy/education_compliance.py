"""Compliance helpers for education-scoped wealth guidance."""

from __future__ import annotations

import re


DISCLAIMER_MESSAGE = (
    "Educational scenario comparison only — not personalized investment advice."
)

_ACTION_THEN_TICKER = re.compile(
    r"\b(buy|sell|hold|short|recommend|purchase)\b.{0,40}\b(\$?[A-Z]{1,5}|[A-Z]{2,6}X)\b"
)
_TICKER_THEN_ACTION = re.compile(
    r"\b(\$?[A-Z]{1,5}|[A-Z]{2,6}X)\b.{0,40}\b(is a buy|is a sell|should buy|should sell|buy now|sell now)\b",
    re.IGNORECASE,
)

BLOCKED_MESSAGE = (
    "Specific ticker buy/sell recommendations are blocked in education mode. "
    "Compare categories and tradeoffs instead."
)


def contains_ticker_recommendation(text: str) -> bool:
    if not text:
        return False
    return bool(_ACTION_THEN_TICKER.search(text) or _TICKER_THEN_ACTION.search(text))


def enforce_education_content(text: str) -> tuple[str, bool]:
    """Return (content, allowed)."""
    if contains_ticker_recommendation(text):
        return BLOCKED_MESSAGE, False
    return text, True
