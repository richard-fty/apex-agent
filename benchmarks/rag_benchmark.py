from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_service import rag_store as rag_store_module
from rag_service.rag_store import RagStore
from rag_service.retrieval import index_path, query_index


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rag"
BENCH_COLLECTION = "rag_benchmark"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_.-]+", text.lower()))


def _deterministic_embed_texts(texts: list[str]) -> list[list[float]]:
    vocabulary = [
        "pineglass",
        "current",
        "old",
        "draft",
        "threshold",
        "0.62",
        "0.41",
        "silver",
        "blue",
        "orchard",
        "ember",
        "relay",
        "vault",
        "owner",
        "tianye",
        "obsolete",
        "apac-lab-2",
        "orchid",
    ]
    vectors: list[list[float]] = []
    for text in texts:
        tokens = _tokenize(text)
        vectors.append([1.0 if token in tokens else 0.0 for token in vocabulary])
    return vectors


def _install_local_test_embeddings() -> None:
    import rag_service.retrieval as retrieval_module

    retrieval_module.embed_texts = _deterministic_embed_texts


def _fresh_store() -> None:
    benchmark_store = Path(".tmp") / "rag_benchmark_store"
    benchmark_store.mkdir(parents=True, exist_ok=True)
    rag_store_module._STORE = RagStore(str(benchmark_store))


def main() -> None:
    _install_local_test_embeddings()
    _fresh_store()

    index_result = index_path(str(FIXTURE_DIR), collection=BENCH_COLLECTION)
    if not index_result["ok"]:
        raise SystemExit(index_result["message"])

    cases = [
        {
            "name": "exact_phrase",
            "query": "What is the Pineglass emergency phrase?",
            "expected_source": "pineglass_current.md",
            "expected_text": "silver orchard",
        },
        {
            "name": "current_threshold",
            "query": "What is the current Pineglass fallback score threshold?",
            "expected_source": "pineglass_current.md",
            "expected_text": "0.62",
        },
        {
            "name": "multi_fact",
            "query": "Who owns Pineglass and what region is active?",
            "expected_source": "pineglass_current.md",
            "expected_text": "apac-lab-2",
        },
        {
            "name": "routing_model",
            "query": "List the Pineglass memory routing stages.",
            "expected_source": "pineglass_current.md",
            "expected_text": "vault",
        },
    ]

    print("RAG benchmark")
    print(f"Indexed files: {index_result['files_indexed']}, chunks: {index_result['total_chunks']}")

    for retrieval_mode in ("vector", "bm25", "hybrid"):
        hits_at_1 = 0
        hits_at_3 = 0
        reciprocal_ranks: list[float] = []
        print("")
        print(f"[mode={retrieval_mode}]")

        for case in cases:
            result = query_index(
                case["query"],
                collection=BENCH_COLLECTION,
                top_k=3,
                retrieval_mode=retrieval_mode,
            )
            rows = result.get("results", [])
            matched_rank = None
            for rank, row in enumerate(rows, start=1):
                source = Path(row["source"]).name
                text = row["text"].lower()
                if source == case["expected_source"] and case["expected_text"].lower() in text:
                    matched_rank = rank
                    break

            if matched_rank == 1:
                hits_at_1 += 1
            if matched_rank is not None and matched_rank <= 3:
                hits_at_3 += 1
                reciprocal_ranks.append(1.0 / matched_rank)
            else:
                reciprocal_ranks.append(0.0)

            top_source = Path(rows[0]["source"]).name if rows else "none"
            top_score = f"{rows[0]['score']:.4f}" if rows else "n/a"
            print(f"- {case['name']}: top1={top_source} score={top_score} matched_rank={matched_rank}")

        total = len(cases)
        mrr = sum(reciprocal_ranks) / total if total else 0.0
        print(f"hit@1: {hits_at_1}/{total} = {hits_at_1 / total:.2%}")
        print(f"hit@3: {hits_at_3}/{total} = {hits_at_3 / total:.2%}")
        print(f"mrr:   {mrr:.4f}")


if __name__ == "__main__":
    main()
