from __future__ import annotations

from agent.policy.education_compliance import (
    BLOCKED_MESSAGE,
    contains_ticker_recommendation,
    enforce_education_content,
)


def test_contains_ticker_recommendation_detects_buy_language() -> None:
    assert contains_ticker_recommendation("You should buy AAPL right now.") is True
    assert contains_ticker_recommendation("SPY is a buy for your portfolio.") is True
    assert contains_ticker_recommendation("Compare T-bills with broad index funds.") is False


def test_enforce_education_content_blocks_specific_ticker_advice() -> None:
    content, allowed = enforce_education_content("I recommend buying NVDA here.")

    assert allowed is False
    assert content == BLOCKED_MESSAGE
