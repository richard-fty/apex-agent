from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from rag_service import rag_store as rag_store_module
from rag_service.rag_store import RagStore
from rag_service.retrieval import index_path, query_index


SQUAD_PATH = Path("/tmp/squad-dev-v1.1.json")
MAX_CASES = 5
HASH_DIM = 256


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_.-]+", text.lower())


def _hash_embed_texts(texts: list[str]) -> list[list[float]]:
    import hashlib

    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * HASH_DIM
        for token in _tokenize(text):
            idx = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % HASH_DIM
            vec[idx] += 1.0
        norm = sum(value * value for value in vec) ** 0.5 or 1.0
        vectors.append([value / norm for value in vec])
    return vectors


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "doc"


def _prepare_squad_sample(doc_dir: Path, max_cases: int = MAX_CASES) -> list[dict[str, str]]:
    payload = json.loads(SQUAD_PATH.read_text(encoding="utf-8"))
    doc_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, str]] = []
    used_contexts: set[str] = set()
    doc_index = 0

    for article in payload["data"]:
        title = article.get("title", "untitled")
        for paragraph in article.get("paragraphs", []):
            context = paragraph.get("context", "").strip()
            if not context or context in used_contexts:
                continue

            qa_candidates = [qa for qa in paragraph.get("qas", []) if qa.get("answers")]
            if not qa_candidates:
                continue

            qa = qa_candidates[0]
            answer = qa["answers"][0]["text"].strip()
            if not answer or answer.lower() not in context.lower():
                continue

            doc_index += 1
            source_name = f"{doc_index:02d}-{_slugify(title)}.md"
            (doc_dir / source_name).write_text(f"# {title}\n\n{context}\n", encoding="utf-8")
            used_contexts.add(context)
            cases.append(
                {
                    "question": qa["question"].strip(),
                    "answer": answer,
                    "source": source_name,
                }
            )
            if len(cases) >= max_cases:
                return cases

    return cases


def _evaluate_mode(collection: str, cases: list[dict[str, str]], retrieval_mode: str) -> dict[str, float]:
    hits_at_1 = 0
    hits_at_3 = 0
    reciprocal_ranks: list[float] = []

    for case in cases:
        result = query_index(
            case["question"],
            collection=collection,
            top_k=3,
            retrieval_mode=retrieval_mode,
        )
        rows = result.get("results", [])
        matched_rank = None
        for rank, row in enumerate(rows, start=1):
            source = Path(row["source"]).name
            text = row["text"].lower()
            if source == case["source"] and case["answer"].lower() in text:
                matched_rank = rank
                break

        if matched_rank == 1:
            hits_at_1 += 1
        if matched_rank is not None and matched_rank <= 3:
            hits_at_3 += 1
            reciprocal_ranks.append(1.0 / matched_rank)
        else:
            reciprocal_ranks.append(0.0)

    total = len(cases)
    return {
        "hit_at_1": hits_at_1 / total,
        "hit_at_3": hits_at_3 / total,
        "mrr": sum(reciprocal_ranks) / total,
    }


@pytest.fixture()
def squad_batch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, list[dict[str, str]]]:
    if not SQUAD_PATH.exists():
        pytest.skip("Missing /tmp/squad-dev-v1.1.json; download the SQuAD dev set first.")

    monkeypatch.setattr("rag_service.retrieval.embed_texts", _hash_embed_texts)
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))

    doc_dir = tmp_path / "squad_docs"
    cases = _prepare_squad_sample(doc_dir)
    assert len(cases) == MAX_CASES

    collection = "squad_batch"
    index_result = index_path(str(doc_dir), collection=collection)
    assert index_result["ok"] is True
    assert index_result["files_indexed"] == MAX_CASES
    return collection, cases


@pytest.mark.parametrize(
    ("retrieval_mode", "min_hit_at_1", "min_hit_at_3"),
    [
        ("vector", 0.20, 0.80),
        ("bm25", 0.60, 0.80),
        ("hybrid", 0.20, 0.80),
    ],
)
def test_squad_batch_benchmark_modes(
    squad_batch_env: tuple[str, list[dict[str, str]]],
    retrieval_mode: str,
    min_hit_at_1: float,
    min_hit_at_3: float,
) -> None:
    collection, cases = squad_batch_env

    metrics = _evaluate_mode(collection, cases, retrieval_mode)

    assert metrics["hit_at_1"] >= min_hit_at_1
    assert metrics["hit_at_3"] >= min_hit_at_3
    assert metrics["mrr"] > 0.0
