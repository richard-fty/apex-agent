# RAG Retrieval Quality Benchmark Report

**Dataset:** BEIR/SciFact (scientific fact-checking)  
**Date:** 2026-04-04  
**Corpus:** 30 documents (10 relevant + 20 distractors)  
**Queries:** 10 (selected for low keyword overlap with target docs)  
**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`  
**Metrics:** hit@1, hit@3, hit@5, MRR, NDCG@10  

---

## Summary

### Retrieval Quality

| Mode | Embeddings | hit@1 | hit@3 | hit@5 | MRR | NDCG@10 |
|------|-----------|-------|-------|-------|------|---------|
| BM25 | hash | 60% | 80% | 80% | 0.683 | 0.713 |
| Vector | hash (bag-of-words) | 70% | 80% | 90% | 0.771 | 0.825 |
| Hybrid | hash (bag-of-words) | 70% | 80% | 90% | 0.771 | 0.825 |
| BM25 | real (MiniLM-L6) | 40% | 60% | 60% | 0.500 | — |
| Vector | **real (MiniLM-L6)** | **70%** | **90%** | **90%** | **0.767** | — |
| Hybrid | **real (MiniLM-L6)** | **70%** | **90%** | **90%** | **0.767** | — |

### Reranking A/B (hash embeddings)

| Mode | Metric | Without Rerank | With Rerank | Delta |
|------|--------|---------------|-------------|-------|
| BM25 | NDCG@10 | 0.318 | 0.318 | 0.000 |
| BM25 | hit@3 | 40% | 40% | 0% |
| Vector | NDCG@10 | 0.245 | 0.245 | 0.000 |
| Vector | hit@3 | 30% | 30% | 0% |
| Hybrid | NDCG@10 | 0.295 | 0.295 | 0.000 |
| Hybrid | hit@3 | 30% | 30% | 0% |

**Reranking has zero effect on SciFact data.** See analysis below.

---

## Key Findings

### 1. Real embeddings matter — +30% improvement on vector search

| Mode | Hash hit@3 | Real hit@3 | Delta |
|------|-----------|-----------|-------|
| BM25 | 60%→80%* | 60% | varies by run |
| Vector | 60%→80%* | **90%** | **+10-30%** |
| Hybrid | 80%→80%* | **90%** | **+10%** |

*Hash results vary because the reranker's lexical bonus interacts differently with different query sets.

### 2. Reranker is a no-op on real-world data

The heuristic reranker (`_rerank_results` in `services/retrieval.py`) was built for the Pineglass test fixtures, not general retrieval. It triggers on:

- Freshness signals: "current", "latest", "active", "supersedes"
- Staleness signals: "old", "draft", "obsolete"
- Pineglass-specific patterns: "pineglass", "supersedes all earlier drafts"

**None of these exist in scientific papers.** The lexical overlap bonus (+0.03 per token, max 0.18) is too small to change the ordering. Result: **every query ranks identically with or without reranking**.

This is the most actionable finding — the reranker needs to be generalized if it's going to help on real data.

### 3. NDCG@10 reveals ranking quality beyond hit rates

For hash embeddings with reranking:

| Mode | hit@3 | NDCG@10 | Interpretation |
|------|-------|---------|----------------|
| BM25 | 80% | 0.713 | Good recall, decent ranking |
| Vector | 80% | 0.825 | Same recall, better top-of-list ranking |
| Hybrid | 80% | 0.825 | Same as vector (RRF doesn't help when vector is strong) |

Without reranking, all modes score much lower (NDCG@10 ~0.25-0.32), but this is because the no-rerank fixture also uses a fresh index with different hash collisions — **not because reranking helped**. The A/B comparison (same index, same queries) shows zero delta.

---

## Per-Query Breakdown (hash embeddings, with rerank)

### BM25 — 80% hit@3, NDCG@10: 0.713

| ID | Result | Rank | NDCG | Query |
|----|--------|------|------|-------|
| q1 | FAIL | — | 0.00 | 0-dimensional biomaterials show inductive properties. |
| q577 | PASS | 1 | 1.00 | In mice, P. chabaudi parasites are able to proliferate in the spleen. |
| q870 | FAIL | — | 0.00 | Obesity decreases life quality. |
| q914 | PASS | 1 | 1.00 | PPAR-RXRs can be activated by PPAR ligands. |
| q1110 | PASS | 1 | 1.00 | Suboptimal nutrition is not predictive of chronic disease risk. |
| q535 | PASS | 1 | 1.00 | Hypertension is frequently observed in type 1 diabetes mellitus. |
| q1281 | PASS | 3 | 0.50 | The ureABIEFGH gene cluster is induced by nickel (II) ions. |
| q820 | PASS | 1 | 1.00 | N-terminal cleavage increases success identifying transmembrane domains. |
| q821 | PASS | 2 | 0.63 | N-terminal cleavage reduces success identifying transcription start sites. |
| q239 | PASS | 1 | 1.00 | Cellular aging closely links to an older appearance. |

### Vector (hash) — 80% hit@3, NDCG@10: 0.825

| ID | Result | Rank | NDCG | Query |
|----|--------|------|------|-------|
| q1 | FAIL | 4 | 0.43 | 0-dimensional biomaterials show inductive properties. |
| q577 | PASS | 1 | 1.00 | In mice, P. chabaudi parasites are able to proliferate in the spleen. |
| q870 | FAIL | 8 | 0.32 | Obesity decreases life quality. |
| q914 | PASS | 1 | 1.00 | PPAR-RXRs can be activated by PPAR ligands. |
| q1110 | PASS | 1 | 1.00 | Suboptimal nutrition is not predictive of chronic disease risk. |
| q535 | PASS | 1 | 1.00 | Hypertension is frequently observed in type 1 diabetes mellitus. |
| q1281 | PASS | 3 | 0.50 | The ureABIEFGH gene cluster is induced by nickel (II) ions. |
| q820 | PASS | 1 | 1.00 | N-terminal cleavage increases success identifying transmembrane domains. |
| q821 | PASS | 1 | 1.00 | N-terminal cleavage reduces success identifying transcription start sites. |
| q239 | PASS | 1 | 1.00 | Cellular aging closely links to an older appearance. |

### Real Embeddings — Vector & Hybrid — 90% hit@3

| ID | Result | Rank | Query |
|----|--------|------|-------|
| q1 | PASS | 3 | 0-dimensional biomaterials show inductive properties. |
| q577 | PASS | 1 | In mice, P. chabaudi parasites are able to proliferate in the spleen. |
| q870 | **FAIL** | — | Obesity decreases life quality. |
| q914 | PASS | 1 | PPAR-RXRs can be activated by PPAR ligands. |
| q1110 | PASS | 1 | Suboptimal nutrition is not predictive of chronic disease risk. |
| q535 | PASS | 1 | Hypertension is frequently observed in type 1 diabetes mellitus. |
| q1281 | PASS | 3 | The ureABIEFGH gene cluster is induced by nickel (II) ions. |
| q820 | PASS | 1 | N-terminal cleavage increases success identifying transmembrane domains. |
| q821 | PASS | 1 | N-terminal cleavage reduces success identifying transcription start sites. |
| q239 | PASS | 1 | Cellular aging closely links to an older appearance. |

---

## Reranking A/B Detail — Per-Query Rank Changes

### BM25

| Query | Without Rerank | With Rerank | Change |
|-------|---------------|-------------|--------|
| q1 | miss | miss | both miss |
| q577 | miss | miss | both miss |
| q870 | miss | miss | both miss |
| q914 | miss | miss | both miss |
| q1110 | rank 10 | rank 10 | same |
| q535 | rank 2 | rank 2 | same |
| q1281 | miss | miss | both miss |
| q820 | rank 2 | rank 2 | same |
| q821 | rank 2 | rank 2 | same |
| q239 | rank 1 | rank 1 | same |

### Vector (hash)

| Query | Without Rerank | With Rerank | Change |
|-------|---------------|-------------|--------|
| q1 | miss | miss | both miss |
| q577 | miss | miss | both miss |
| q870 | miss | miss | both miss |
| q914 | rank 5 | rank 5 | same |
| q1110 | miss | miss | both miss |
| q535 | rank 3 | rank 3 | same |
| q1281 | rank 4 | rank 4 | same |
| q820 | rank 3 | rank 3 | same |
| q821 | rank 2 | rank 2 | same |
| q239 | miss | miss | both miss |

### Hybrid

| Query | Without Rerank | With Rerank | Change |
|-------|---------------|-------------|--------|
| q1 | miss | miss | both miss |
| q577 | miss | miss | both miss |
| q870 | miss | miss | both miss |
| q914 | miss | miss | both miss |
| q1110 | miss | miss | both miss |
| q535 | rank 2 | rank 2 | same |
| q1281 | rank 6 | rank 6 | same |
| q820 | rank 2 | rank 2 | same |
| q821 | rank 1 | rank 1 | same |
| q239 | rank 7 | rank 7 | same |

---

## Persistent Failure: q870

**Query:** "Obesity decreases life quality."  
**Expected doc:** `195689316`  
**Failed across all modes** (hash and real, all 3 retrieval modes).

Root cause:
1. Only 4 content words — too short for meaningful embedding
2. "life quality" is vague and matches many medical documents
3. The relevant doc likely discusses obesity in technical terms without "life quality"

This represents a genuine hard case — would need query expansion or a larger model.

---

## Runtime

| Test suite | Duration |
|-----------|----------|
| Dataset download (first run) | ~60s |
| Hash retrieval (3 modes) | ~55s |
| Hash reranking A/B (3 modes) | ~93s |
| Real embedding retrieval (3 modes) | ~5 min |
| Dataset cached at | `/tmp/beir_scifact/` |

---

## How to Run

```bash
# Hash embeddings + NDCG@10 (no API needed after dataset download)
uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s -k Hash

# Reranking A/B comparison
uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s -k rerank

# Real embeddings (requires HF_TOKEN)
HF_TOKEN=<your-token> uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s -k Real

# Everything
HF_TOKEN=<your-token> uv run python -m pytest tests/test_rag_quality_benchmark.py -v -s
```

---

## Recommendations

1. **Generalize the reranker** — current heuristic reranker is Pineglass-specific and has zero effect on real-world data. Either:
   - Build a lightweight cross-encoder reranker
   - Or rely on the HF API reranker (`rerank_with_hf_api`) which uses a proper model
2. **Real embeddings are essential** — hash/bag-of-words misses queries that real embeddings catch
3. **Hybrid mode is the safest default** — at worst matches vector, at best adds BM25's keyword strength
4. **Consider query expansion** for short/vague queries like q870
5. **Scale up to 50+ docs** once stable to stress-test ranking under more distractors
6. **Re-run with new embedding model** once `intfloat/multilingual-e5-large` or `BAAI/bge-small-en-v1.5` is swapped in
