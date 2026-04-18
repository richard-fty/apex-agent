from __future__ import annotations

import re
from pathlib import Path

import pytest

from rag_service import rag_store as rag_store_module
from rag_service.rag_store import RagStore
from rag_service.retrieval import chunk_text, index_path, query_index


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rag"


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


@pytest.fixture()
def rag_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr("rag_service.retrieval.embed_texts", _deterministic_embed_texts)
    rag_store_module._STORE = RagStore(str(tmp_path / "rag_store"))
    return FIXTURE_DIR


def test_chunk_text_creates_multiple_overlapping_chunks() -> None:
    lines = [f"line {i}: Pineglass detail" for i in range(1, 80)]
    text = "\n".join(lines)

    chunks = chunk_text(text, "memory_note.md")

    assert len(chunks) > 1
    first = chunks[0]["metadata"]
    second = chunks[1]["metadata"]
    assert second["start_line"] <= first["end_line"]
    assert all(chunk["text"].strip() for chunk in chunks)


def test_query_index_returns_exact_current_fact(rag_test_env: Path) -> None:
    result = index_path(str(rag_test_env), collection="rag_test")
    assert result["ok"] is True
    assert result["files_indexed"] == 3

    query = query_index(
        "What is the Pineglass emergency phrase?",
        collection="rag_test",
        top_k=3,
    )

    assert query["ok"] is True
    assert query["results"]
    top_text = query["results"][0]["text"].lower()
    assert "silver orchard" in top_text


def test_query_index_prefers_current_doc_over_old_draft(rag_test_env: Path) -> None:
    result = index_path(str(rag_test_env), collection="rag_rank")
    assert result["ok"] is True

    query = query_index(
        "What is the current Pineglass fallback score threshold?",
        collection="rag_rank",
        top_k=3,
    )

    assert query["ok"] is True
    assert len(query["results"]) >= 2

    top = query["results"][0]
    assert top["source"].endswith("pineglass_current.md")
    assert "0.62" in top["text"]

    returned_sources = [item["source"] for item in query["results"]]
    assert any(source.endswith("pineglass_old_draft.md") for source in returned_sources)


def test_query_index_hybrid_mode_returns_current_doc(rag_test_env: Path) -> None:
    result = index_path(str(rag_test_env), collection="rag_hybrid")
    assert result["ok"] is True

    query = query_index(
        "What is the current Pineglass fallback score threshold?",
        collection="rag_hybrid",
        top_k=3,
        retrieval_mode="hybrid",
    )

    assert query["ok"] is True
    top = query["results"][0]
    assert top["retrieval_mode"] == "hybrid"
    assert top["source"].endswith("pineglass_current.md")
    assert "0.62" in top["text"]
