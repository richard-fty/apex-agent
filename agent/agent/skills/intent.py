"""Skill-intent strategies.

Two production-grade approaches, selected by pack count:

  N ≤ 10  →  LLMNativeStrategy
    Do not pre-load. The Level-1 index is already in the system prompt; the
    model picks via the `load_skill` meta-tool when needed. One extra
    round-trip in the unlucky case, but no speculative token spend.

  10 < N ≤ 50  →  HybridStrategy
    BM25 over pack text (description + keywords + SKILL.md) fused with optional
    vector cosine via Reciprocal Rank Fusion. Normalized to 0–1 so callers can
    use a single threshold.

  N > 50  →  raise; multi-stage retrieval not implemented yet.

The loader chooses the strategy once at `discover()`. Callers only see
`select(user_input) -> list[pack_name]`.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from typing import Callable

from skill_packs.base import SkillPack


EmbedFn = Callable[[str], list[float]]


# ── tokenizer & helpers ────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── BM25 ────────────────────────────────────────────────────────────────


class BM25:
    """Minimal BM25 implementation (Okapi, k1=1.5, b=0.75)."""

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.N = len(corpus_tokens) or 1
        self.doc_lens = [len(d) for d in corpus_tokens]
        self.avgdl = sum(self.doc_lens) / self.N if self.N else 0.0

        # term frequencies per doc + document frequency per term
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for tokens in corpus_tokens:
            counts: dict[str, int] = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1

        self.idf = {
            t: math.log(((self.N - freq + 0.5) / (freq + 0.5)) + 1.0)
            for t, freq in df.items()
        }

    def score(self, query_tokens: list[str]) -> list[float]:
        if not self.doc_lens:
            return []
        scores = [0.0] * self.N
        for t in query_tokens:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf_doc in enumerate(self.tf):
                f = tf_doc.get(t, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_lens[i] / self.avgdl)
                scores[i] += idf * (f * (self.k1 + 1)) / denom
        return scores


# ── fusion ──────────────────────────────────────────────────────────────


def _rrf_fuse(ranking_lists: list[list[int]], n_docs: int, k: int = 60) -> list[float]:
    """Reciprocal Rank Fusion over ranked index lists. Returns per-doc scores."""
    scores = [0.0] * n_docs
    for ranking in ranking_lists:
        for rank, doc_idx in enumerate(ranking, start=1):
            scores[doc_idx] += 1.0 / (k + rank)
    return scores


def _minmax_normalize(scores: list[float]) -> list[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [0.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


# ── strategies ──────────────────────────────────────────────────────────


class IntentStrategy(ABC):
    """Decide which packs to pre-load for a given user input."""

    @abstractmethod
    def select(self, user_input: str, threshold: float = 0.6) -> list[str]:
        """Return pack names to pre-load (may be empty)."""


class LLMNativeStrategy(IntentStrategy):
    """At small scale (≤ 10 packs), trust the model + Level-1 index.

    The system prompt already carries the Level-1 index for every installed
    pack (~20 tokens each). Rather than guessing via retrieval, we let the
    model issue `load_skill(name)` if it judges a pack is relevant. One extra
    round-trip in the unlucky case; zero speculative token spend in the
    common case where no pack is needed.
    """

    def select(self, user_input: str, threshold: float = 0.6) -> list[str]:
        return []


class HybridStrategy(IntentStrategy):
    """BM25 + (optional) vector cosine, fused via RRF.

    Why hybrid: BM25 handles exact terms (tickers, acronyms like RSI/MACD);
    vector handles synonyms and paraphrases ("invest" ≈ "trade"). RRF fuses
    without needing comparable score scales.

    `embed_fn` is optional. Without it, this degrades to BM25-only, which is
    still a strict improvement over keyword counting because it's TF-IDF
    weighted and length-normalized.
    """

    def __init__(self, packs: list[SkillPack], embed_fn: EmbedFn | None = None) -> None:
        self.packs = list(packs)
        self.embed_fn = embed_fn

        self._doc_tokens = [_tokenize(self._doc_text(p)) for p in self.packs]
        self._bm25 = BM25(self._doc_tokens)

        self._pack_embeddings: list[list[float]] | None = None
        if self.embed_fn is not None and self.packs:
            try:
                self._pack_embeddings = [self.embed_fn(self._doc_text(p)) for p in self.packs]
            except Exception:
                # any embedding failure at init time → fall back to BM25-only
                self._pack_embeddings = None

    @staticmethod
    def _doc_text(pack: SkillPack) -> str:
        parts = [pack.name, pack.description, " ".join(pack.keywords)]
        skill_md = pack.skill_md
        if skill_md:
            parts.append(skill_md[:1500])
        return " ".join(parts)

    # Minimum cosine a pack needs for vector-only to count as a real signal.
    # Under real embeddings (e.g. bge-m3) cosine > 0.3 typically indicates
    # topical relatedness. Prevents off-topic queries from pinning a pack just
    # because it happens to rank highest among uniformly-irrelevant options.
    VECTOR_SIGNAL_FLOOR = 0.3

    def select(self, user_input: str, threshold: float = 0.6) -> list[str]:
        if not self.packs:
            return []

        query_tokens = _tokenize(user_input)
        bm25_scores = self._bm25.score(query_tokens)

        vec_scores: list[float] = [0.0] * len(self.packs)
        has_vector = False
        if self._pack_embeddings is not None and self.embed_fn is not None:
            try:
                q_emb = self.embed_fn(user_input)
                vec_scores = [_cosine(q_emb, e) for e in self._pack_embeddings]
                has_vector = True
            except Exception:
                # Transient embedding failure: fall back to BM25-only this turn
                has_vector = False

        bm25_rank = sorted(range(len(self.packs)), key=lambda i: -bm25_scores[i])
        rankings = [bm25_rank]
        if has_vector:
            vec_rank = sorted(range(len(self.packs)), key=lambda i: -vec_scores[i])
            rankings.append(vec_rank)

        fused = _rrf_fuse(rankings, n_docs=len(self.packs))
        normed_fused = _minmax_normalize(fused)

        selected: list[str] = []
        for idx in range(len(self.packs)):
            if normed_fused[idx] < threshold:
                continue
            # A pack must show meaningful signal from at least one ranker —
            # min-max normalization will always produce a "top" pack even for
            # irrelevant queries, so the gate prevents off-topic false positives.
            has_signal = bm25_scores[idx] > 0 or (
                has_vector and vec_scores[idx] >= self.VECTOR_SIGNAL_FLOOR
            )
            if has_signal:
                selected.append(self.packs[idx].name)
        return selected


# ── selector ────────────────────────────────────────────────────────────


LLM_NATIVE_THRESHOLD = 10
HYBRID_MAX = 50


def choose_strategy(packs: list[SkillPack], embed_fn: EmbedFn | None = None) -> IntentStrategy:
    """Pick the right strategy based on how many packs are installed."""
    n = len(packs)
    if n <= LLM_NATIVE_THRESHOLD:
        return LLMNativeStrategy()
    if n <= HYBRID_MAX:
        return HybridStrategy(packs, embed_fn=embed_fn)
    raise ValueError(
        f"{n} skill packs is beyond the current retrieval envelope "
        f"(> {HYBRID_MAX}). Implement multi-stage retrieval with an LLM "
        f"reranker before scaling further."
    )
