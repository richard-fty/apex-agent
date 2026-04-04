from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from rag_service import rag_store as rag_store_module
from rag_service.rag_store import RagStore
from rag_service.retrieval import index_path, query_index


SQUAD_PATH = Path("/tmp/squad-dev-v1.1.json")
DOC_DIR = ROOT / ".tmp" / "squad_sample_docs"
BENCH_COLLECTION = "squad_sample"
MAX_DOCS = 20
HASH_DIM = 256


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "doc"


def _fresh_store() -> None:
    benchmark_store = ROOT / ".tmp" / "squad_sample_store"
    if benchmark_store.exists():
        shutil.rmtree(benchmark_store)
    benchmark_store.mkdir(parents=True, exist_ok=True)
    rag_store_module._STORE = RagStore(str(benchmark_store))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_.-]+", text.lower())


def _hash_embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * HASH_DIM
        for token in _tokenize(text):
            vec[hash(token) % HASH_DIM] += 1.0
        norm = sum(value * value for value in vec) ** 0.5 or 1.0
        vectors.append([value / norm for value in vec])
    return vectors


def _install_local_embeddings_fallback() -> None:
    import rag_service.retrieval as retrieval_module

    retrieval_module.embed_texts = _hash_embed_texts


def _prepare_sample() -> list[dict[str, str]]:
    payload = json.loads(SQUAD_PATH.read_text())
    data = payload["data"]

    if DOC_DIR.exists():
        shutil.rmtree(DOC_DIR)
    DOC_DIR.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, str]] = []
    used_contexts: set[str] = set()
    doc_index = 0

    for article in data:
        title = article.get("title", "untitled")
        for paragraph in article.get("paragraphs", []):
            context = paragraph.get("context", "").strip()
            if not context or context in used_contexts:
                continue
            qa_candidates = [
                qa for qa in paragraph.get("qas", [])
                if qa.get("answers")
            ]
            if not qa_candidates:
                continue

            qa = qa_candidates[0]
            answer = qa["answers"][0]["text"].strip()
            if not answer or answer.lower() not in context.lower():
                continue

            doc_index += 1
            source_name = f"{doc_index:02d}-{_slugify(title)}.md"
            source_path = DOC_DIR / source_name
            source_path.write_text(f"# {title}\n\n{context}\n", encoding="utf-8")

            used_contexts.add(context)
            cases.append(
                {
                    "question": qa["question"].strip(),
                    "answer": answer,
                    "source": source_name,
                }
            )
            if len(cases) >= MAX_DOCS:
                return cases

    return cases


def main() -> None:
    if not SQUAD_PATH.exists():
        raise SystemExit(
            "Missing /tmp/squad-dev-v1.1.json. Download the SQuAD dev set first."
        )

    if not settings.hf_token:
        _install_local_embeddings_fallback()

    _fresh_store()
    cases = _prepare_sample()
    if not cases:
        raise SystemExit("Failed to prepare a SQuAD sample benchmark.")

    index_result = index_path(str(DOC_DIR), collection=BENCH_COLLECTION)
    if not index_result["ok"]:
        raise SystemExit(index_result["message"])

    print("SQuAD sample benchmark")
    print(f"Prepared docs/questions: {len(cases)}")
    print(f"Indexed files: {index_result['files_indexed']}, chunks: {index_result['total_chunks']}")
    if not settings.hf_token:
        print("Embedding backend: local hash fallback (HF_TOKEN not set)")

    for retrieval_mode in ("vector", "bm25", "hybrid"):
        hits_at_1 = 0
        hits_at_3 = 0
        reciprocal_ranks: list[float] = []

        print("")
        print(f"[mode={retrieval_mode}]")

        for case in cases:
            result = query_index(
                case["question"],
                collection=BENCH_COLLECTION,
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
        mrr = sum(reciprocal_ranks) / total if total else 0.0
        print(f"hit@1: {hits_at_1}/{total} = {hits_at_1 / total:.2%}")
        print(f"hit@3: {hits_at_3}/{total} = {hits_at_3 / total:.2%}")
        print(f"mrr:   {mrr:.4f}")


if __name__ == "__main__":
    main()
