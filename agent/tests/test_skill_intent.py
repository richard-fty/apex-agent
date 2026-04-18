"""Tests for the two-strategy skill intent matcher."""

from __future__ import annotations

from typing import Any

import pytest

from agent.skills.intent import (
    BM25,
    HYBRID_MAX,
    HybridStrategy,
    LLM_NATIVE_THRESHOLD,
    LLMNativeStrategy,
    _cosine,
    _tokenize,
    choose_strategy,
)


class FakePack:
    """Minimal SkillPack stand-in — avoids filesystem SKILL.md reads."""

    def __init__(self, name: str, description: str, keywords: list[str]) -> None:
        self.name = name
        self.description = description
        self.keywords = keywords

    @property
    def skill_md(self) -> str:
        return ""


# ── tokenizer ──────────────────────────────────────────────────────────


def test_tokenize_lowercases_and_keeps_hyphens() -> None:
    assert _tokenize("Analyze BTC-USD vs ETH-USD") == ["analyze", "btc-usd", "vs", "eth-usd"]


def test_tokenize_drops_punctuation() -> None:
    assert _tokenize("Hello, world! What is 2+2?") == ["hello", "world", "what", "is", "2", "2"]


# ── BM25 ───────────────────────────────────────────────────────────────


def test_bm25_ranks_relevant_doc_highest() -> None:
    corpus = [
        ["stock", "trading", "strategy", "backtest"],
        ["research", "report", "document", "analysis"],
        ["customer", "service", "ticket", "refund"],
    ]
    bm25 = BM25(corpus)
    scores = bm25.score(["stock", "trading"])
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]


def test_bm25_unknown_term_returns_zero() -> None:
    corpus = [["hello", "world"]]
    bm25 = BM25(corpus)
    assert bm25.score(["qxyz"]) == [0.0]


def test_bm25_empty_corpus_returns_empty() -> None:
    bm25 = BM25([])
    assert bm25.score(["anything"]) == []


# ── cosine ─────────────────────────────────────────────────────────────


def test_cosine_identical_vectors() -> None:
    assert _cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors() -> None:
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_handles_zero_vectors() -> None:
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── LLMNativeStrategy ──────────────────────────────────────────────────


def test_llm_native_never_preloads() -> None:
    strategy = LLMNativeStrategy()
    assert strategy.select("analyze AAPL stock trading strategy") == []
    assert strategy.select("") == []


# ── HybridStrategy (BM25-only) ─────────────────────────────────────────


def test_hybrid_bm25_only_picks_relevant_pack() -> None:
    packs = [
        FakePack("stock_strategy",
                 "Stock and crypto analysis — fetch market data, compute indicators, backtest strategies",
                 ["stock", "trading", "backtest", "aapl", "btc-usd", "rsi", "macd"]),
        FakePack("research_report",
                 "Read multiple sources and write a structured cited report",
                 ["research", "report", "cite", "summarize", "compare"]),
        FakePack("customer_service",
                 "Handle customer tickets, refunds, and account operations",
                 ["ticket", "refund", "customer", "account", "cancel"]),
    ]
    strategy = HybridStrategy(packs, embed_fn=None)
    selected = strategy.select("Please backtest an RSI strategy on AAPL", threshold=0.5)
    assert selected == ["stock_strategy"]


def test_hybrid_rejects_when_no_pack_matches() -> None:
    packs = [
        FakePack("stock_strategy", "Stock analysis", ["stock", "trading"]),
        FakePack("research_report", "Research reports", ["research", "report"]),
    ]
    strategy = HybridStrategy(packs, embed_fn=None)
    assert strategy.select("what is the weather today?", threshold=0.6) == []


def test_hybrid_empty_pack_list() -> None:
    strategy = HybridStrategy([], embed_fn=None)
    assert strategy.select("anything", threshold=0.5) == []


# ── HybridStrategy (with embed_fn) ─────────────────────────────────────


def _fake_embed(text: str) -> list[float]:
    """Deterministic toy embedding: 4-dim, one axis per topic keyword."""
    t = text.lower()
    return [
        1.0 if any(k in t for k in ("stock", "trade", "invest", "market", "aapl")) else 0.0,
        1.0 if any(k in t for k in ("research", "report", "summary", "analysis")) else 0.0,
        1.0 if any(k in t for k in ("customer", "refund", "ticket", "account")) else 0.0,
        0.1,  # constant tiny term so vectors are never pure-zero
    ]


def test_hybrid_with_vector_prefers_semantic_match() -> None:
    packs = [
        FakePack("stock_strategy", "Stock analysis", ["stock", "trading", "aapl"]),
        FakePack("research_report", "Research reports", ["research", "report"]),
        FakePack("customer_service", "Customer handling", ["customer", "refund"]),
    ]
    strategy = HybridStrategy(packs, embed_fn=_fake_embed)
    selected = strategy.select("I want to invest in Apple", threshold=0.5)
    assert "stock_strategy" in selected


def test_hybrid_vector_failure_falls_back_to_bm25() -> None:
    def flaky_embed(text: str) -> list[float]:
        raise RuntimeError("embedding service down")

    packs = [
        FakePack("stock_strategy", "Stock analysis", ["stock", "trading", "aapl"]),
        FakePack("research_report", "Research reports", ["research", "report"]),
    ]
    # Init-time failure should produce a BM25-only strategy that still works
    strategy = HybridStrategy(packs, embed_fn=flaky_embed)
    assert strategy.select("backtest AAPL trading strategy", threshold=0.5) == ["stock_strategy"]


# ── choose_strategy ────────────────────────────────────────────────────


def _make_packs(n: int) -> list[FakePack]:
    return [FakePack(f"pack_{i}", f"desc_{i}", [f"kw_{i}"]) for i in range(n)]


def test_choose_strategy_small_returns_llm_native() -> None:
    for n in (0, 1, 5, LLM_NATIVE_THRESHOLD):
        strategy = choose_strategy(_make_packs(n))
        assert isinstance(strategy, LLMNativeStrategy), f"n={n}"


def test_choose_strategy_medium_returns_hybrid() -> None:
    for n in (LLM_NATIVE_THRESHOLD + 1, 25, HYBRID_MAX):
        strategy = choose_strategy(_make_packs(n))
        assert isinstance(strategy, HybridStrategy), f"n={n}"


def test_choose_strategy_too_many_raises() -> None:
    with pytest.raises(ValueError, match="multi-stage retrieval"):
        choose_strategy(_make_packs(HYBRID_MAX + 1))
