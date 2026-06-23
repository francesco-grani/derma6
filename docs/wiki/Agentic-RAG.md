# Agentic RAG Pipeline

The `kb_search` tool runs a 7-node LangGraph `StateGraph` that implements four agentic retrieval patterns. The outer ReAct agent, FastAPI layer, and API contract are completely unchanged — the pipeline lives entirely inside the tool boundary.

---

## Pipeline topology

```
query_decompose
      │
hybrid_retrieve   ←── HyDE dense (ChromaDB) + BM25 sparse, merged via RRF
      │
   rerank         ←── cross-encoder vs original query
      │
 crag_grade       ←── LLM grades each doc as relevant / not relevant
      │
  ┌───┴──────────────────────────────────────────────────────┐
  │ score ≥ threshold                  score < threshold     │
  ▼                                          ▼               │
generate                            local_retry              │
  ▲                                  (reformulate +          │
  │                                   re-retrieve +          │
  │                                   re-grade)              │
  │                                          │               │
  │                        score ≥ threshold │               │
  ├──────────────────────────────────────────┘               │
  │                        score < threshold                 │
  │                                          ▼               │
  └──────────────────────── external_fallback ───────────────┘
                            (web-search → llm-only)
```

### Why this order matters

1. **Local KB stays authoritative.** CRAG always tries a local retry before going external. External fallback (web search or LLM-only) is a last resort, not a first resort.
2. **BM25 + dense = better recall.** Exact ingredient names (`tretinoin`, `niacinamide`) are keyword matches that dense embeddings can miss. BM25 catches them reliably. RRF merges both without requiring calibrated scores.
3. **Cross-encoder after RRF = better precision.** RRF maximises recall cheaply; the cross-encoder re-reads the query + each chunk together and re-ranks by actual relevance.

---

## Node reference

### `query_decompose`

Splits a complex question into focused sub-queries using an LLM call.

- **Input:** `original_query`
- **Output:** `sub_queries` (list), `decompose_error` (bool)
- **Fallback:** on LLM error or timeout → `sub_queries = [original_query]`
- **Timeout:** `DECOMPOSE_TIMEOUT_SECONDS` (default: 10 s)

Prompt skeleton:
```
Return ONLY a JSON array of strings covering the full intent of the question.
If the question is already simple and atomic, return it unchanged.
```

---

### `hybrid_retrieve`

Runs dense and sparse retrieval **in parallel** for each sub-query, then merges with RRF.

**Dense path (HyDE):**
1. LLM generates a short hypothetical answer for the sub-query (3–5 sentence factual passage).
2. The hypothetical is embedded with `OpenRouterEmbeddings.embed_query()`.
3. ChromaDB is queried with that embedding instead of the raw question.
4. On HyDE failure: raw sub-query text is embedded directly; `hyde_fallback_count` is incremented.

**Sparse path (BM25):**
- `BM25Index` is built once at startup from the full ChromaDB corpus (whitespace tokenised).
- Queried with the raw sub-query text.
- On failure: dense-only retrieval continues; `bm25_fallback_count` is incremented.

**RRF merge:**
```
RRF_score(d) = Σ_i  1 / (k + rank(L_i, d) + 1)    k = RRF_K (default: 60)
```
Results from all sub-queries are then merged by summing RRF scores across sub-queries (documents relevant to multiple sub-topics score higher), and deduplicated by `doc_id`.

- **Timeout:** `HYDE_TIMEOUT_SECONDS` (default: 10 s) per sub-query HyDE call

---

### `rerank`

Scores the RRF-merged candidate set using a cross-encoder model loaded at startup.

- Model: `RERANKER_MODEL` (default: `cross-encoder/ms-marco-MiniLM-L-6-v2`, ~22 MB CPU)
- Scores each `(original_query, chunk_content)` pair.
- Sorts descending; truncates to `RERANK_TOP_K` (default: 5).
- On failure: original RRF order is preserved; `rerank_error = True`.
- **Timeout:** `RERANK_TIMEOUT_SECONDS` (default: 15 s)

The cross-encoder sees the **original** query (before decomposition), ensuring final ranking reflects what the user actually asked.

---

### `crag_grade`

Grades each reranked document for relevance using concurrent LLM calls.

- Prompt: binary yes/no per doc (`doc.content[:500]` vs `original_query`).
- Aggregate score: `count(yes) / total`.
- **Routes to `generate`** if `score ≥ CRAG_RELEVANCE_THRESHOLD` (default: 0.5).
- **Routes to `local_retry`** otherwise (including empty doc list or timeout).
- **Timeout:** `CRAG_GRADE_TIMEOUT_SECONDS` (default: 10 s) for the full grading pass.

Enable `RAG_DEBUG_MODE=true` to log each doc's grade with its `doc_id` and source.

---

### `local_retry`

Reformulates the original query and re-runs the full retrieval pipeline from scratch.

1. LLM rewrites `original_query` using more precise terminology.
2. `hybrid_retrieve` + `rerank` run with the reformulated query.
3. Results are re-graded with the same CRAG logic.
4. If `retry_score ≥ threshold` → routes to `generate` with `final_routing = "local-retry-succeeded"`.
5. If still below threshold → routes to `external_fallback`.

The local KB is always tried twice before giving up.

---

### `external_fallback`

Only reached when both first-pass grading and local retry fail.

| `CRAG_FALLBACK_STRATEGY` | Behaviour |
|---|---|
| `llm-only` (default) | LLM answers from parametric knowledge; disclaimer prepended to response |
| `web-search` | Tavily (if `TAVILY_API_KEY` set) or DuckDuckGo; degrades to `llm-only` on failure |

The disclaimer for `llm-only`:
> Note: The local knowledge base did not contain sufficient relevant information for this query. The following response is based on general knowledge and should be verified with authoritative skincare sources.

---

### `generate`

Formats the final context string in the same format as the original `kb_search` output so no downstream code changes are needed.

```
<chunk 1>

---

<chunk 2>

Sources: Guide Name, ...

__RAG_CONTEXT_JSON__: [{"source": "...", "score": 0.9, "snippet": "..."}]

__RAG_PIPELINE_META__: {"final_routing": "generate", "rag_fallback_triggered": false, "retry_triggered": false}
```

The `__RAG_CONTEXT_JSON__` block is parsed by the existing `extract_rag_context()` function (unchanged). The new `__RAG_PIPELINE_META__` block is parsed by `extract_rag_pipeline_meta()` and surfaced in the SSE `metadata` event as `rag_routing` and `rag_fallback_triggered`.

---

## Configuration reference

All parameters load from environment variables with safe defaults. No new required variables — the app starts with only `OPENROUTER_API_KEY` set.

| Environment variable | Type | Default | Description |
|---|---|---|---|
| `RERANKER_MODEL` | str | `cross-encoder/ms-marco-MiniLM-L-6-v2` | HuggingFace model ID for the cross-encoder |
| `RERANK_TOP_K` | int | `5` | Chunks kept after reranking |
| `CRAG_RELEVANCE_THRESHOLD` | float | `0.5` | Minimum fraction of relevant docs to proceed to generation |
| `CRAG_FALLBACK_STRATEGY` | str | `llm-only` | `"llm-only"` or `"web-search"` |
| `DECOMPOSE_TIMEOUT_SECONDS` | int | `10` | Max seconds for query decomposition |
| `HYDE_TIMEOUT_SECONDS` | int | `10` | Max seconds per HyDE generation call |
| `CRAG_GRADE_TIMEOUT_SECONDS` | int | `10` | Max seconds for the full grading pass |
| `RERANK_TIMEOUT_SECONDS` | int | `15` | Max seconds for cross-encoder reranking |
| `RRF_K` | int | `60` | RRF smoothing constant |
| `TAVILY_API_KEY` | str | `""` | Tavily API key (if empty and `web-search`, DuckDuckGo is used) |
| `RAG_DEBUG_MODE` | bool | `false` | Log sub-queries, hypothetical docs, and per-doc CRAG grades |

---

## Observability

Every pipeline invocation emits a structured `INFO` log at the end of `generate`:

```json
{
  "event": "rag_pipeline_complete",
  "sub_query_count": 2,
  "hyde_fallback_count": 0,
  "bm25_fallback_count": 0,
  "dense_only_count": 3,
  "sparse_only_count": 1,
  "rrf_merged_count": 8,
  "chunk_count_after_rerank": 5,
  "first_pass_score": 0.8,
  "retry_triggered": false,
  "retry_score": null,
  "final_routing": "generate",
  "total_latency_ms": 1450,
  "node_latencies_ms": {
    "query_decompose": 340,
    "hybrid_retrieve": 710,
    "rerank": 85,
    "crag_grade": 210,
    "generate": 5
  }
}
```

The SSE `metadata` event gains two new fields:

```json
{
  "type": "metadata",
  "rag_routing": "generate",
  "rag_fallback_triggered": false,
  "citations": [...],
  "rag_context": [...]
}
```

`rag_routing` is one of: `"generate"`, `"local-retry-succeeded"`, `"web-search"`, `"llm-only"`.

---

## Package layout

```
backend/rag/pipeline/
    __init__.py          # exports RagPipelineGraph, RagState, RankedDoc
    state.py             # RagState TypedDict, RankedDoc dataclass, initial_state()
    bm25_index.py        # BM25Index singleton + get_bm25_index() + reset_bm25_index()
    graph.py             # StateGraph builder + RagPipelineGraph class
    nodes/
        decompose.py     # query_decompose node
        retrieve.py      # hybrid_retrieve node
        rerank.py        # rerank node + CrossEncoder singleton
        crag.py          # crag_grade, local_retry, route_after_crag, route_after_retry
        generate.py      # generate node
        fallback.py      # external_fallback node
        _rrf.py          # rrf_merge() and merge_sub_query_results() utilities
```

---

## Latency budget

Rough per-node overhead on a developer machine (single user, `gpt-4o-mini`):

| Node | Typical latency |
|---|---|
| `query_decompose` | 300–800 ms |
| `hybrid_retrieve` | 600–1 200 ms (HyDE LLM + embed + ChromaDB + BM25 in parallel) |
| `rerank` | 50–150 ms (cross-encoder, CPU, 5–20 docs) |
| `crag_grade` | 150–500 ms (concurrent LLM calls) |
| `local_retry` (if triggered) | +1–2 s |
| `external_fallback` (if triggered) | +1–3 s |

Total happy-path overhead vs baseline `retriever.query()`: roughly **1–2.5 s** before the final LLM generation call.

---

## Known limitations

- **BM25 corpus staleness** — the in-memory index is built at startup. If `scripts/index_kb.py --reset` is run while the app is running, restart the backend to rebuild it.
- **Cross-encoder cold start** — the first request after a cold start loads the model weights (~22 MB, 2–4 s). Pre-download the model into the Docker image or trigger a warm-up `/health` call.
- **CRAG grading cost** — 5 LLM calls per request reaching CRAG. With `gpt-4o-mini`, this is roughly $0.0001/request at default `RERANK_TOP_K=5`.
- **Web search privacy** — if `CRAG_FALLBACK_STRATEGY=web-search`, the reformulated query is sent to Tavily or DuckDuckGo. Default is `llm-only`; opt in explicitly.
