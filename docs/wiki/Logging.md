# Logging

**TL;DR** — Two independent knobs: `LOG_LEVEL` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`, default `INFO`) sets which records are *emitted*; `RAG_DEBUG_MODE` (default `false`) decides whether the RAG pipeline *creates* its per-step debug records at all. To watch a query unfold step by step you need **both** — `LOG_LEVEL=DEBUG` alone shows nothing extra from the pipeline. Logs go to stdout (`docker compose logs`) and to a rotating `logs/app.log`.

---

## The two knobs

| Variable | Default | Values | What it does |
|---|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Root logger threshold — the floor for what reaches stdout and the log file. |
| `RAG_DEBUG_MODE` | `false` | `true` / `false` | Gates the `logger.debug(...)` calls inside the RAG pipeline nodes. |
| `LOG_FILE` | `./logs/app.log` | path | Rotating file target (10 MB × 3 backups). |

They are not redundant, and this catches people out. `RAG_DEBUG_MODE` guards the *call sites* in
[`nodes/decompose.py`](../../backend/rag/pipeline/nodes/decompose.py),
[`nodes/retrieve.py`](../../backend/rag/pipeline/nodes/retrieve.py) and
[`nodes/crag.py`](../../backend/rag/pipeline/nodes/crag.py) — with it off, those records are never
created, so no `LOG_LEVEL` can surface them. `LOG_LEVEL` then decides whether records that *were*
created get emitted. The useful combinations:

| `LOG_LEVEL` | `RAG_DEBUG_MODE` | Result |
|---|---|---|
| `INFO` | `false` | **Production default.** Milestones only: retries, pipeline completion, request lines. |
| `INFO` | `true` | Nothing extra — the debug records are created, then dropped below the threshold. Pointless. |
| `DEBUG` | `false` | Debug from the agent and elsewhere, but the RAG pipeline stays quiet. |
| `DEBUG` | `true` | **Full narration.** Sub-queries, HyDE docs, per-doc CRAG grades. |

### Levels in practice

`WARNING` and above are rarely what you want here: the app logs almost all of its useful
observability at `INFO`, so `WARNING` hides the pipeline entirely and leaves you with only
failures. `ERROR`/`CRITICAL` are for when you only care that something broke.

> **A typo takes the backend down.** `LOG_LEVEL` has no validator
> ([`config.py`](../../backend/config.py)); the string is handed to `Logger.setLevel()`, which
> raises `ValueError: Unknown level: 'VERBOSE'` at startup. Only the five names above are valid,
> and `TRACE`/`VERBOSE`/`WARN` are **not** among them. Values are upper-cased, so `debug` is fine.

## Turning it on

Locally, in `.env`:

```bash
LOG_LEVEL=DEBUG
RAG_DEBUG_MODE=true
```

On the Hetzner box — note `.env` is excluded from the deploy rsync, so a server-side edit
persists across deploys and must be reverted by hand:

```bash
ssh root@167.233.84.81
cd /app
sed -i 's/^LOG_LEVEL=.*/LOG_LEVEL=DEBUG/' .env
sed -i 's/^RAG_DEBUG_MODE=.*/RAG_DEBUG_MODE=true/' .env   # append if absent
docker compose up -d backend                              # recreate to pick up env
```

Revert with the same edits back to `INFO` / `false`, then `docker compose up -d backend`.

## Reading the logs

Format is `ISO-timestamp | LEVEL | username | component | message`, where `username` comes from a
per-request `ContextVar` (`-` outside a request).

```bash
# Live tail of the backend container
ssh -o ServerAliveInterval=30 root@167.233.84.81 \
  "cd /app && docker compose logs -f --tail=50 backend"

# Persistent file (survives container restarts)
ssh root@167.233.84.81 "tail -f /app/logs/app.log"
```

`Batches: ...` progress bars come from `sentence_transformers` writing to stderr directly (not via
`logging`), so no log level suppresses them. Filter them out when tailing:

```bash
... | grep -v 'Batches:'
```

### There is no frontend log

The frontend is a static build served by Caddy from `/app/www` — there is no dev server and no
terminal output. Use the browser devtools console. Caddy has no `log` directive in the
[`Caddyfile`](../../Caddyfile), so it emits no access log either; `/api/*` requests are visible as
uvicorn access lines in the **backend** stream instead.

## What you see at DEBUG

A single query narrates itself end to end:

```
DEBUG | derma6.rag.decompose | Decomposed sub-query[0]: 'What is retinol and how does it work on skin?'
DEBUG | derma6.rag.decompose | Decomposed sub-query[1]: 'What are the potential side effects of retinol for beginners?'
INFO  | derma6.rag.bm25      | BM25 index built: 418 documents in 0.15s
DEBUG | derma6.rag.retrieve  | HyDE doc for 'What is retinol...': # Retinol in Skincare
INFO  | derma6.rag.rerank    | CrossEncoder loaded: cross-encoder/ms-marco-MiniLM-L-6-v2 in 3.3s
DEBUG | derma6.rag.crag      | CRAG grade: doc_id='...retinol.md::chunk_0' source='Retinol Profile' relevant=True
INFO  | derma6.rag           | local_retry: reformulated query='...'
INFO  | derma6.rag           | rag_pipeline_complete | sub_query_count=5 chunk_count_after_rerank=4 ...
```

### Structured fields

[`nodes/generate.py`](../../backend/rag/pipeline/nodes/generate.py) attaches a 12-field
observability payload to `rag_pipeline_complete` via `extra={...}` — routing decision, per-node
latencies, retry state, fusion counts. The stdlib formatter discards `extra`, so
[`logging_config.py`](../../backend/logging_config.py) installs `_ExtraFieldFormatter` to append it:

```
rag_pipeline_complete | sub_query_count=5 chunk_count_after_rerank=4 first_pass_score=0.75
  retry_triggered=False final_routing=generate total_latency_ms=8423
  node_latencies_ms={'decompose': 900, 'retrieve': 3100, 'rerank': 210}
```

`final_routing` is the single most useful field — it names the path the pipeline actually took
(`generate`, `local-retry-succeeded`, `web-search`, `llm-only-salvaged`, `llm-only`) and is the
same value the chat UI shows as a badge in its Tools panel. See
[Agentic RAG](Agentic-RAG.md) for what each route means.

## Third-party noise

At `DEBUG` the root threshold would otherwise propagate into every HTTP library. Measured on one
RAG query: ~200 lines from `httpcore.http11`, ~80 from `httpcore.connection`, ~52 from
`openai._base_client`, ~51 from `urllib3.connectionpool` — against ~19 useful `derma6.rag` lines.

`setup_logging()` therefore pins these regardless of `LOG_LEVEL`:

| Logger | Pinned to | Why |
|---|---|---|
| `httpx`, `httpcore`, `openai`, `urllib3`, `sentence_transformers`, `chromadb` | `WARNING` | Per-socket/per-request chatter that buries the pipeline. |
| `chromadb.telemetry` | `CRITICAL` | Telemetry only. |
| `langsmith.client` | `ERROR` | Emits a multi-line `WARNING` per trace when the tenant is over its monthly quota — not actionable from here. Genuine client failures still surface. |

To debug one of those libraries, raise it explicitly rather than lifting the pin for all of them:

```python
logging.getLogger("httpx").setLevel(logging.DEBUG)
```

## Error monitoring

`SENTRY_DSN` enables Sentry (`SENTRY_TRACES_SAMPLE_RATE`, default `0.1`); unset, `init_sentry()`
logs a warning and disables itself. `LANGSMITH_API_KEY` enables LangSmith tracing — see
[Agentic RAG](Agentic-RAG.md). Both are independent of `LOG_LEVEL`.
