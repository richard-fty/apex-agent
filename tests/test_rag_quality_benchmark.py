"""RAG retrieval quality benchmark using BEIR/SciFact dataset.

SciFact is a popular IR benchmark with 5,183 scientific documents and
300 fact-checking queries with human-judged relevance labels. We sample
a small batch (30 docs, 10 queries) to stay within HF API rate limits.

Benchmark coverage:
  - Retrieval quality: hit@1, hit@3, hit@5, MRR, NDCG@10
  - Reranking A/B: same metrics with reranking on vs off
  - Two embedding modes: hash (deterministic) vs real (HF API)

Usage:
  uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s
  uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s -k real     # real embeddings
  uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s -k rerank   # reranking A/B

The dataset is auto-downloaded to /tmp/beir_scifact/ on first run (~3 MB).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from rag_service import rag_store as rag_store_module
from rag_service.rag_store import RagStore
from rag_service.retrieval import index_path, query_index

# ---------------------------------------------------------------------------
# Dataset config
# ---------------------------------------------------------------------------

SCIFACT_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip"
SCIFACT_CACHE = Path("/tmp/beir_scifact")
MAX_QUERIES = 10  # number of queries to sample
MAX_EXTRA_DOCS = 20  # distractor docs beyond the relevant ones

HASH_DIM = 256

# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------


def _download_scifact() -> Path:
    """Download and extract SciFact to /tmp/beir_scifact if not cached."""
    marker = SCIFACT_CACHE / "scifact" / "corpus.jsonl"
    if marker.exists():
        return SCIFACT_CACHE / "scifact"

    SCIFACT_CACHE.mkdir(parents=True, exist_ok=True)
    print(f"Downloading SciFact dataset from {SCIFACT_URL} ...")
    resp = httpx.get(SCIFACT_URL, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(SCIFACT_CACHE)

    assert marker.exists(), f"Expected {marker} after extraction"
    print(f"SciFact cached at {SCIFACT_CACHE / 'scifact'}")
    return SCIFACT_CACHE / "scifact"


def _load_scifact(
    data_dir: Path,
    max_queries: int = MAX_QUERIES,
    max_extra_docs: int = MAX_EXTRA_DOCS,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Load a small sample from SciFact.

    Returns:
        corpus_subset: {doc_id: "title\\n\\ntext"} for docs to index
        test_cases: [{query, relevant_doc_ids}] with ground-truth labels
    """
    # Load full corpus into memory (it's small — ~5K docs)
    corpus: dict[str, dict[str, str]] = {}
    with open(data_dir / "corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            corpus[str(doc["_id"])] = {
                "title": doc.get("title", ""),
                "text": doc.get("text", ""),
            }

    # Load queries
    queries: dict[str, str] = {}
    with open(data_dir / "queries.jsonl", encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            queries[str(q["_id"])] = q["text"]

    # Load qrels (relevance judgments)
    qrels: dict[str, dict[str, int]] = {}  # query_id -> {doc_id: score}
    qrels_path = data_dir / "qrels" / "test.tsv"
    with open(qrels_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader, None)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            qid, did, score = row[0], row[1], int(row[2])
            if score > 0:  # only positive relevance
                qrels.setdefault(qid, {})[did] = score

    # Score each query by keyword overlap with its relevant doc —
    # pick queries with LOW overlap so hash embeddings can't trivially win.
    def _token_set(text: str) -> set[str]:
        return set(re.findall(r"[a-z]{3,}", text.lower()))

    candidates: list[tuple[float, dict[str, Any]]] = []
    for qid, rel_docs in qrels.items():
        if qid not in queries:
            continue
        valid_docs = {did for did in rel_docs if did in corpus}
        if not valid_docs:
            continue
        query_tokens = _token_set(queries[qid])
        if len(query_tokens) < 3:
            continue
        # Measure max Jaccard similarity with any relevant doc
        max_sim = 0.0
        for did in valid_docs:
            doc_tokens = _token_set(corpus[did]["title"] + " " + corpus[did]["text"])
            intersection = len(query_tokens & doc_tokens)
            union = len(query_tokens | doc_tokens)
            if union > 0:
                max_sim = max(max_sim, intersection / union)
        candidates.append((max_sim, {
            "query_id": qid,
            "query": queries[qid],
            "relevant_doc_ids": valid_docs,
        }))

    # Sort by ascending overlap — hardest queries first
    candidates.sort(key=lambda x: x[0])

    sampled_cases: list[dict[str, Any]] = []
    relevant_doc_ids: set[str] = set()
    for _sim, case in candidates[:max_queries]:
        sampled_cases.append(case)
        relevant_doc_ids.update(case["relevant_doc_ids"])

    # Build corpus subset: relevant docs + distractor docs
    corpus_subset: dict[str, str] = {}
    for did in relevant_doc_ids:
        doc = corpus[did]
        corpus_subset[did] = f"# {doc['title']}\n\n{doc['text']}"

    # Add distractor docs (not relevant to any sampled query)
    added = 0
    for did, doc in corpus.items():
        if did in relevant_doc_ids:
            continue
        corpus_subset[did] = f"# {doc['title']}\n\n{doc['text']}"
        added += 1
        if added >= max_extra_docs:
            break

    return corpus_subset, sampled_cases


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


def _hash_embed_texts(texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-words embedding (no API)."""
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * HASH_DIM
        for token in re.findall(r"[a-z0-9_.-]+", text.lower()):
            vec[hash(token) % HASH_DIM] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


# ---------------------------------------------------------------------------
# NDCG@10 computation
# ---------------------------------------------------------------------------


def _dcg(relevances: list[float], k: int = 10) -> float:
    """Discounted Cumulative Gain at rank k."""
    score = 0.0
    for i, rel in enumerate(relevances[:k]):
        score += rel / math.log2(i + 2)  # i+2 because rank starts at 1
    return score


def _ndcg_at_k(relevances: list[float], k: int = 10) -> float:
    """Normalized DCG@k — 1.0 means perfect ranking, 0.0 means no relevant docs found."""
    dcg = _dcg(relevances, k)
    ideal = _dcg(sorted(relevances, reverse=True), k)
    return dcg / ideal if ideal > 0 else 0.0


# ---------------------------------------------------------------------------
# Reranking passthrough (for A/B test)
# ---------------------------------------------------------------------------


def _no_rerank(
    query: str,
    results: list[tuple[Any, float]],
) -> list[tuple[Any, float]]:
    """Identity function — returns results unchanged, bypassing reranking."""
    return results


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _run_evaluation(
    collection: str,
    cases: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """Evaluate retrieval for all cases. Returns metrics + per-query details."""
    hits_1 = 0
    hits_3 = 0
    hits_5 = 0
    rr_sum = 0.0
    ndcg_sum = 0.0
    details: list[dict[str, Any]] = []

    for case in cases:
        result = query_index(
            case["query"],
            collection=collection,
            top_k=10,
            retrieval_mode=mode,
        )
        rows = result.get("results", [])

        # Build relevance vector for NDCG@10
        relevances: list[float] = []
        for row in rows[:10]:
            source_name = Path(row["source"]).stem
            rel = 1.0 if source_name in case["relevant_doc_ids"] else 0.0
            relevances.append(rel)

        ndcg = _ndcg_at_k(relevances, k=10)
        ndcg_sum += ndcg

        # Find first relevant result
        matched_rank = None
        for rank, row in enumerate(rows, start=1):
            source_name = Path(row["source"]).stem
            if source_name in case["relevant_doc_ids"]:
                matched_rank = rank
                break

        if matched_rank == 1:
            hits_1 += 1
        if matched_rank is not None and matched_rank <= 3:
            hits_3 += 1
        if matched_rank is not None and matched_rank <= 5:
            hits_5 += 1
        rr_sum += (1.0 / matched_rank) if matched_rank else 0.0

        details.append({
            "query_id": case["query_id"],
            "query": case["query"],
            "relevant_ids": case["relevant_doc_ids"],
            "matched_rank": matched_rank,
            "ndcg_10": ndcg,
            "hit_at_3": matched_rank is not None and matched_rank <= 3,
            "top_5_sources": [Path(r["source"]).stem for r in rows[:5]],
        })

    n = len(cases)
    return {
        "mode": mode,
        "hit_at_1": hits_1 / n,
        "hit_at_3": hits_3 / n,
        "hit_at_5": hits_5 / n,
        "mrr": rr_sum / n,
        "ndcg_10": ndcg_sum / n,
        "total": n,
        "hits_1": hits_1,
        "hits_3": hits_3,
        "hits_5": hits_5,
        "details": details,
    }


def _print_report(metrics: dict[str, Any], label: str = "") -> None:
    """Print a human-readable benchmark report."""
    tag = f" [{label}]" if label else ""
    print(f"\n{'=' * 80}")
    print(
        f"  BEIR/SciFact{tag} | Mode: {metrics['mode']:7s} | "
        f"hit@1: {metrics['hit_at_1']:.0%}  hit@3: {metrics['hit_at_3']:.0%}  "
        f"hit@5: {metrics['hit_at_5']:.0%}  MRR: {metrics['mrr']:.3f}  "
        f"NDCG@10: {metrics['ndcg_10']:.3f}"
    )
    print(f"  ({metrics['total']} queries, {metrics['hits_3']}/{metrics['total']} hit@3)")
    print(f"{'=' * 80}")

    for d in metrics["details"]:
        status = "PASS" if d["hit_at_3"] else "FAIL"
        rank_str = f"rank={d['matched_rank']}" if d["matched_rank"] else "not found"
        print(
            f"  [{status}] q{d['query_id']:>4s} {rank_str:14s} "
            f"ndcg={d['ndcg_10']:.2f} | {d['query'][:50]}"
        )
        if not d["hit_at_3"]:
            print(f"         relevant: {d['relevant_ids']}")
            print(f"         got top5: {d['top_5_sources']}")
    print()


def _print_rerank_comparison(
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    """Print side-by-side reranking A/B comparison."""
    print(f"\n{'=' * 80}")
    print(f"  RERANKING A/B  |  Mode: {before['mode']}")
    print(f"{'=' * 80}")
    print(f"  {'Metric':<12s} {'Without Rerank':>15s} {'With Rerank':>15s} {'Delta':>10s}")
    print(f"  {'-' * 52}")
    for key, label in [
        ("hit_at_1", "hit@1"),
        ("hit_at_3", "hit@3"),
        ("hit_at_5", "hit@5"),
        ("mrr", "MRR"),
        ("ndcg_10", "NDCG@10"),
    ]:
        b = before[key]
        a = after[key]
        delta = a - b
        sign = "+" if delta > 0 else ""
        fmt = ".0%" if key.startswith("hit") else ".3f"
        print(
            f"  {label:<12s} {b:>15{fmt}} {a:>15{fmt}} {sign}{delta:>9{fmt}}"
        )
    print()

    # Per-query rank changes
    print(f"  {'Query':<8s} {'Before':>8s} {'After':>8s} {'Change':>10s}")
    print(f"  {'-' * 34}")
    for bd, ad in zip(before["details"], after["details"]):
        br = bd["matched_rank"]
        ar = ad["matched_rank"]
        br_str = str(br) if br else "miss"
        ar_str = str(ar) if ar else "miss"
        if br and ar:
            change = br - ar  # positive = improved (lower rank is better)
            if change > 0:
                ch_str = f"+{change} better"
            elif change < 0:
                ch_str = f"{change} worse"
            else:
                ch_str = "same"
        elif ar and not br:
            ch_str = "rescued!"
        elif br and not ar:
            ch_str = "LOST"
        else:
            ch_str = "both miss"
        print(f"  q{bd['query_id']:>5s} {br_str:>8s} {ar_str:>8s} {ch_str:>10s}")
    print()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scifact_data() -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Download SciFact and return (corpus_subset, test_cases)."""
    try:
        data_dir = _download_scifact()
    except Exception as exc:
        pytest.skip(f"Cannot download SciFact: {exc}")
    corpus_subset, test_cases = _load_scifact(data_dir)
    assert len(test_cases) >= 5, f"Only got {len(test_cases)} test cases"
    return corpus_subset, test_cases


def _index_corpus(
    tmp_path: Path,
    corpus_subset: dict[str, str],
    collection: str,
) -> str:
    """Write corpus files to disk and index them. Returns collection name."""
    doc_dir = tmp_path / "scifact_docs"
    doc_dir.mkdir(exist_ok=True)
    for doc_id, text in corpus_subset.items():
        (doc_dir / f"{doc_id}.md").write_text(text, encoding="utf-8")

    result = index_path(str(doc_dir), collection=collection)
    assert result["ok"] is True
    assert result["files_indexed"] == len(corpus_subset)
    return collection


@pytest.fixture()
def corpus_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scifact_data: tuple[dict[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Index SciFact subset with hash embeddings."""
    corpus_subset, test_cases = scifact_data
    monkeypatch.setattr("rag_service.retrieval.embed_texts", _hash_embed_texts)
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    collection = _index_corpus(tmp_path, corpus_subset, "scifact_hash")
    return collection, test_cases


@pytest.fixture()
def corpus_real(
    tmp_path: Path,
    scifact_data: tuple[dict[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Index SciFact subset with real embeddings (SiliconFlow or HF)."""
    if not os.environ.get("SILICONFLOW_API_KEY") and not os.environ.get("HF_TOKEN"):
        pytest.skip("Set SILICONFLOW_API_KEY or HF_TOKEN to run with real embeddings")
    corpus_subset, test_cases = scifact_data
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    collection = _index_corpus(tmp_path, corpus_subset, "scifact_real")
    return collection, test_cases


@pytest.fixture()
def corpus_hash_no_rerank(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scifact_data: tuple[dict[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Index with hash embeddings, reranking disabled."""
    corpus_subset, test_cases = scifact_data
    monkeypatch.setattr("rag_service.retrieval.embed_texts", _hash_embed_texts)
    monkeypatch.setattr("rag_service.retrieval._rerank_results", _no_rerank)
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    collection = _index_corpus(tmp_path, corpus_subset, "scifact_hash_nr")
    return collection, test_cases


@pytest.fixture()
def corpus_hash_with_rerank(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scifact_data: tuple[dict[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Index with hash embeddings, reranking enabled (default behavior)."""
    corpus_subset, test_cases = scifact_data
    monkeypatch.setattr("rag_service.retrieval.embed_texts", _hash_embed_texts)
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    collection = _index_corpus(tmp_path, corpus_subset, "scifact_hash_wr")
    return collection, test_cases


@pytest.fixture()
def corpus_real_no_rerank(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scifact_data: tuple[dict[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Index with real embeddings, reranking disabled."""
    if not os.environ.get("SILICONFLOW_API_KEY") and not os.environ.get("HF_TOKEN"):
        pytest.skip("Set SILICONFLOW_API_KEY or HF_TOKEN to run with real embeddings")
    corpus_subset, test_cases = scifact_data
    monkeypatch.setattr("rag_service.retrieval._rerank_results", _no_rerank)
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    collection = _index_corpus(tmp_path, corpus_subset, "scifact_real_nr")
    return collection, test_cases


@pytest.fixture()
def corpus_real_with_rerank(
    tmp_path: Path,
    scifact_data: tuple[dict[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Index with real embeddings, reranking enabled (default behavior)."""
    if not os.environ.get("SILICONFLOW_API_KEY") and not os.environ.get("HF_TOKEN"):
        pytest.skip("Set SILICONFLOW_API_KEY or HF_TOKEN to run with real embeddings")
    corpus_subset, test_cases = scifact_data
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    collection = _index_corpus(tmp_path, corpus_subset, "scifact_real_wr")
    return collection, test_cases


# ---------------------------------------------------------------------------
# Tests — hash embeddings (always runs, needs network once for dataset)
# ---------------------------------------------------------------------------

class TestSciFact_Hash:
    """Pipeline + BM25 correctness with hash embeddings on SciFact data."""

    def test_bm25(self, corpus_hash: tuple[str, list[dict[str, Any]]]) -> None:
        collection, cases = corpus_hash
        metrics = _run_evaluation(collection, cases, "bm25")
        _print_report(metrics)
        # BM25 is keyword-based; queries are selected for low keyword overlap
        assert metrics["hit_at_5"] >= 0.20, f"BM25 hit@5: {metrics['hit_at_5']:.0%}"

    def test_vector_hash(self, corpus_hash: tuple[str, list[dict[str, Any]]]) -> None:
        collection, cases = corpus_hash
        metrics = _run_evaluation(collection, cases, "vector")
        _print_report(metrics)
        # Hash embeddings = bag-of-words on hard queries — expect low scores
        assert metrics["hit_at_5"] >= 0.10, f"Vector(hash) hit@5: {metrics['hit_at_5']:.0%}"

    def test_hybrid_hash(self, corpus_hash: tuple[str, list[dict[str, Any]]]) -> None:
        collection, cases = corpus_hash
        metrics = _run_evaluation(collection, cases, "hybrid")
        _print_report(metrics)
        assert metrics["hit_at_5"] >= 0.20, f"Hybrid(hash) hit@5: {metrics['hit_at_5']:.0%}"


# ---------------------------------------------------------------------------
# Tests — real embeddings (runs only with HF_TOKEN)
# ---------------------------------------------------------------------------

class TestSciFact_Real:
    """Semantic retrieval quality with real embeddings on SciFact data.

    This is the real benchmark — tests whether your RAG pipeline can
    find relevant scientific documents using semantic understanding.
    """

    def test_bm25_real(self, corpus_real: tuple[str, list[dict[str, Any]]]) -> None:
        collection, cases = corpus_real
        metrics = _run_evaluation(collection, cases, "bm25")
        _print_report(metrics)
        assert metrics["hit_at_5"] >= 0.40

    def test_vector_real(self, corpus_real: tuple[str, list[dict[str, Any]]]) -> None:
        collection, cases = corpus_real
        metrics = _run_evaluation(collection, cases, "vector")
        _print_report(metrics)
        assert metrics["hit_at_5"] >= 0.50, f"Vector(real) hit@5: {metrics['hit_at_5']:.0%}"
        assert metrics["mrr"] >= 0.30

    def test_hybrid_real(self, corpus_real: tuple[str, list[dict[str, Any]]]) -> None:
        collection, cases = corpus_real
        metrics = _run_evaluation(collection, cases, "hybrid")
        _print_report(metrics)
        assert metrics["hit_at_5"] >= 0.50, f"Hybrid(real) hit@5: {metrics['hit_at_5']:.0%}"
        assert metrics["mrr"] >= 0.35


# ---------------------------------------------------------------------------
# Tests — Reranking A/B (does reranking improve ranking?)
# ---------------------------------------------------------------------------

class TestRerank_AB_Hash:
    """Reranking A/B with hash embeddings (heuristic reranker only)."""

    @pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
    def test_rerank_hash(
        self,
        corpus_hash_no_rerank: tuple[str, list[dict[str, Any]]],
        corpus_hash_with_rerank: tuple[str, list[dict[str, Any]]],
        mode: str,
    ) -> None:
        coll_nr, cases = corpus_hash_no_rerank
        coll_wr, _ = corpus_hash_with_rerank

        metrics_before = _run_evaluation(coll_nr, cases, mode)
        metrics_after = _run_evaluation(coll_wr, cases, mode)

        _print_report(metrics_before, label="NO rerank (hash)")
        _print_report(metrics_after, label="WITH rerank (hash)")
        _print_rerank_comparison(metrics_before, metrics_after)

        assert metrics_after["ndcg_10"] >= metrics_before["ndcg_10"] - 0.05, (
            f"Reranking degraded NDCG@10: "
            f"{metrics_before['ndcg_10']:.3f} → {metrics_after['ndcg_10']:.3f}"
        )


class TestRerank_AB_Real:
    """Reranking A/B with real embeddings + API reranker (SiliconFlow/HF).

    This is the real test — does the bge-reranker-v2-m3 API improve
    ranking quality over raw retrieval scores?
    """

    @pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
    def test_rerank_real(
        self,
        corpus_real_no_rerank: tuple[str, list[dict[str, Any]]],
        corpus_real_with_rerank: tuple[str, list[dict[str, Any]]],
        mode: str,
    ) -> None:
        coll_nr, cases = corpus_real_no_rerank
        coll_wr, _ = corpus_real_with_rerank

        metrics_before = _run_evaluation(coll_nr, cases, mode)
        metrics_after = _run_evaluation(coll_wr, cases, mode)

        _print_report(metrics_before, label="NO rerank (real)")
        _print_report(metrics_after, label="WITH rerank (real)")
        _print_rerank_comparison(metrics_before, metrics_after)

        assert metrics_after["ndcg_10"] >= metrics_before["ndcg_10"] - 0.05, (
            f"Reranking degraded NDCG@10: "
            f"{metrics_before['ndcg_10']:.3f} → {metrics_after['ndcg_10']:.3f}"
        )
