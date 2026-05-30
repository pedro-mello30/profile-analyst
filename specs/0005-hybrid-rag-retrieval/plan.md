# Plan 0005 — Hybrid RAG Retrieval (Vector + Graph + Keyword)

Derived from `spec.md`. Single-PR-per-track landing; tracks are dependency-ordered.
This spec adds **Stage 8 EMBED** and a read-only **Hybrid RAG** query surface on top of the
existing pipeline (0001 Stages 1–3+6, 0002 Stage 7 LOAD, 0003 Ollama backend). It does **not**
modify any 0001–0003 stage behavior; it adds embedding properties + indexes to the 0002 graph and
a new retrieval/answer path. **No GDS plugin required** (0005 reads 0004's signals when present but
does not compute them).

## Architecture (reference)

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                   profile_analyst.py  (CLI)                       │
  │  --handle <ig>  --stage 8 | all      --rag "<question>"          │
  └──────────┬───────────────────────────────────┬──────────────────┘
             │ (0002 Stage 7 LOAD produced the graph)                │
  ┌──────────▼───────────────────────┐  ┌─────────▼──────────────────┐
  │  Stage 8  EMBED                   │  │  tools/rag.py               │
  │  pipeline/stage8_embed.py         │  │  HybridRAGOrchestrator      │
  │  text_hash gate → embed → upsert  │  │  embed q → 3 retrievers →   │
  │  c.embedding / m.embedding        │  │  RRF fuse → (rerank?) →     │
  │  ensure vector + fulltext indexes │  │  OllamaBackend gen → cite   │
  │  → 08-embed-manifest.json         │  │  → <ts>-rag.json manifest   │
  │    (09-embed.schema.json)         │  │    (10-rag.schema.json)     │
  └──────────┬────────────────────────┘  └─────────┬──────────────────┘
             │                                       │
  ┌──────────▼───────────────────────────────────────▼──────────────┐
  │  Neo4j 5.13+ (Community)        bolt://localhost:7687            │
  │  0002 graph + creator_embeddings / media_embeddings (vector)    │
  │             + creator_fulltext / media_fulltext (BM25)          │
  └──────────────────────────────────────────────────────────────────┘
             │                                       │
  ┌──────────▼───────────────────────────────────────▼──────────────┐
  │  Ollama (localhost:11434)  embed: nomic-embed-text · gen: 0003   │
  └──────────────────────────────────────────────────────────────────┘

  Retrieval legs: VectorRetriever · KeywordRetriever · GraphRetriever (reuses 0003 NL→Cypher)
  Driver:         0002 official `neo4j` driver — read sessions for retrieval, one write for Stage 8
```

Stage 8 is **idempotent**: a node is re-embedded only when its `text_hash` or
`embedding_model_version` changed (re-running on unchanged data is a zero-write no-op). The Hybrid
RAG path is **read-only** over the graph; its only writes are Stage 8's embedding upserts. All
embedding, retrieval, optional rerank, and generation run **on-host** (`data_egress: local-only`).

## Implementation tracks (dependency-ordered)

### Track A — Schemas, config, deps, index migration (foundation)

- Write `schemas/09-embed.schema.json` (draft-7) for `08-embed-manifest.json`: required
  `handle`, `embedded_at`, `embedding_model`, `embedding_model_version`, `dimensions`,
  `similarity_function`, `counts` (`embedded` / `skipped` / `reembedded` for Creator + Media),
  `data_egress` (`local-only`).
- Write `schemas/10-rag.schema.json` (draft-7) for `<ts>-rag.json`: required `question`,
  `modes_run`, `retrievers` (per-mode `k` / `candidates` / `latency_ms` + `error?`),
  `fusion` (`method` / `rrf_k` / `weights` / `fused_candidates`), `rerank` (`enabled` / `model`),
  `generation` (`model` / `latency_ms`), `answer`, `citations[]`, `row_counts`, `latency_ms`,
  `data_egress`, `asked_at`.
- Extend `tools/validate.py` so `make validate` checks both new schemas.
- Add deps: local embedding via Ollama (no new Python lib beyond an HTTP client; reuse 0003's
  `pipeline/llm/ollama_client.py`); optional `[rag]` extra for the cross-encoder reranker
  (sentence-transformers) — off by default, not installed for v1.
- Add env config from spec §11 (`OLLAMA_EMBED_MODEL`, `EMBED_DIMENSIONS`, `RAG_VECTOR_K`,
  `RAG_KEYWORD_K`, `RAG_GRAPH_K`, `RAG_MODES`, `RAG_RRF_K`, `RAG_MODE_WEIGHTS`,
  `RAG_FUSED_TOP_K`, `RAG_RERANK`, `RAG_RERANK_MODEL`, `RAG_RERANK_INPUT`, `RAG_RERANK_OUTPUT`);
  document in CLAUDE.md / `.env` example.
- Add `make embed HANDLE=<handle>`, `make rag HANDLE=<handle> Q="<question>"`, and
  `make rag-rerank HANDLE=<handle> Q="<question>"` targets.

**Exit:** `make validate` green with both new schemas; env documented; Makefile targets present.

---

### Track B — Index migration on the 0002 graph (depends on A)

Implements spec §10.1 (the required 0002 amendment), but owned by 0005 so 0002 gains no dependency.

- Write `pipeline/rag/indexes.py` — `ensure_rag_indexes(session, dimensions, similarity)` runs the
  `CREATE VECTOR INDEX creator_embeddings / media_embeddings IF NOT EXISTS` (dim + cosine from
  config) and `CREATE FULLTEXT INDEX creator_fulltext / media_fulltext IF NOT EXISTS` statements
  from spec §10.1. Idempotent; verifies Neo4j ≥ 5.13 and fails with a clear version error otherwise.
- Confirm dim in `EMBED_DIMENSIONS` matches the embedding model's actual output (probe via
  `OllamaEmbedder.get_dimension()`); refuse to create an index on a mismatch.

**Exit:** against a local Neo4j 5.13+, `ensure_rag_indexes` runs twice with no error and the four
indexes exist with the configured dimension/similarity.

---

### Track C — Ollama embedding client (depends on A)

- Write `pipeline/llm/ollama_embed.py` — `OllamaEmbedder` over Ollama `/api/embeddings`
  (spec §4.2): `embed(texts)` (single or batch), `get_dimension()` (probe), reuses 0003's
  `OLLAMA_HOST` / `keep_alive`. Raises the 0003 `OllamaError` on connection failure (clear
  "Ollama unreachable at $OLLAMA_HOST" message).
- Pure-ish: HTTP only, no Neo4j; unit-testable with a mocked transport.

**Exit:** `embed("hi")` returns a 768-vector against a running Ollama; `get_dimension()` == 768
for `nomic-embed-text`; connection failure raises the documented error (A11).

---

### Track D — Stage 8 EMBED orchestrator (depends on B, C)

Write `pipeline/stage8_embed.py` — `Stage8EmbedProcessor`. Orchestrates:
1. Resolve `embedding_model` + `embedding_model_version` + `dimensions` from config.
2. `ensure_rag_indexes(session, …)` (Track B).
3. Read embeddable text per node from the **graph** (Creator: `username`+`display_name`+`bio`
   +niche signals; Media: `caption_text`), restricted to nodes that passed the 0002 governance
   gate (C5).
4. **Idempotency gate:** compute `text_hash(source_text)`; skip nodes whose stored `text_hash`
   and `embedding_model_version` are unchanged; re-embed the rest.
5. Embed (batched) via `OllamaEmbedder`; **upsert** `embedding` + `embedding_model_version` +
   `text_hash` onto each `Creator` (key `user_id`) / `Media` (key `media_id`) — per 0002 §5.1.
   Hashtags/@mentions preserved verbatim for the full-text index (spec §5.1).
6. Write `08-embed-manifest.json` (atomic `*.tmp` → `os.replace`), schema-validated; record
   `{embedded, skipped, reembedded}` counts and `data_egress: local-only`.

All Cypher parameterized; batched via `UNWIND $rows`. One write session only.

**Exit:** `--stage 8` on a 0002-loaded handle populates embeddings, creates the indexes, and writes
a schema-valid manifest (A1); a second run does zero re-embeds (A2).

---

### Track E — Retrievers (depends on B, C; graph leg depends on 0003)

Write `pipeline/rag/retrievers.py` — three adapters returning a common dict shape
(`{user_id, username, score, source}`), each capped and independently testable:
- `VectorRetriever.retrieve(embedding, k)` → `db.index.vector.queryNodes` over
  `creator_embeddings` / `media_embeddings` (read session).
- `KeywordRetriever.retrieve(query, k)` → `db.index.fulltext.queryNodes` over
  `creator_fulltext` / `media_fulltext` (read session) — recovers `#ad`/`@handle`/SKU.
- `GraphRetriever.retrieve(nl_query, k)` → **delegates to 0003 `tools/ask.py` NL→Cypher**; all
  S1–S6 safety gates + read-only txn apply; Creator identity via `user_id`, traversal via
  `HAS_MEDIA` (never `POSTED`). When 0004 GDS signals exist, they are available to the generated
  Cypher and to ranking (spec §6.2).

**Exit:** each retriever returns ranked candidates against a seeded local graph; vector recalls a
paraphrase miss (A3); keyword recalls an exact token a low vector score missed (A4); graph routes
through the 0003 gated path (A5).

---

### Track F — Fusion + optional rerank (depends on A)

- Write `pipeline/rag/fusion.py` — `RRFFusion` (spec §7.1): `RRF_K = 60` (named, `RAG_RRF_K`
  overridable), per-mode `RAG_MODE_WEIGHTS` (named constants), media→creator roll-up by **max**
  (OQ4 default), truncate to `RAG_FUSED_TOP_K`. Deterministic; pure (no I/O), fully unit-testable.
- Write `pipeline/rag/rerank.py` — `CrossEncoderReranker` (spec §7.2): **no-op when
  `RAG_RERANK=false`** (default); when on, re-scores fused top-K → top-N with a local model
  (`RAG_RERANK_MODEL`, behind the `[rag]` extra). Local-only; records model in the manifest.

**Exit:** a unit test on fixed per-mode rankings yields the documented fused order with overridable
weights (A6); `RAG_RERANK=true` reranks and records the model, default `false` loads no rerank
model (A7).

---

### Track G — Orchestrator + generation (depends on D, E, F; gen reuses 0003)

Write `tools/rag.py` — `HybridRAGOrchestrator.query(question, handle=None)`:
1. Embed the question once (Track C).
2. `_run_retrievers` — run active `RAG_MODES` in parallel with the **graceful-degradation**
   structure (spec §4.3): a single-mode failure contributes zero candidates and is logged;
   all-empty raises a clear `RAGError`.
3. Fuse (Track F) → optional rerank → top-N.
4. Expand candidates into a context block (metrics, niche, `Signal`/`Score` with `confidence` /
   `method` / `art9_risk`, matched media snippets); generate **once** via 0003 `OllamaBackend`
   (model resolved from 0003 config — never hardcoded), grounded-only + cited (spec §8).
5. Surface Art. 9 notice when any candidate carries `art9_risk:true`; include Art. 22 signal
   lineage for any ranking (spec §9 C3/C4).
6. Write `<ts>-rag.json` atomically; schema-validate; `data_egress: local-only`.
   `--handle` is an optional graph filter; default whole-graph corpus (OQ5).

**Exit:** `--rag "<q>"` returns a grounded, cited answer with a schema-valid manifest (A8); a
zero-result query states so without fabrication (A8); manifest records `local-only` (A9).

---

### Track H — CLI wiring + tests (depends on D, G)

- Extend `profile_analyst.py`: `--stage 8` (include 8 in `all`), `--rag "<q>"`, `--modes`,
  `--rerank`. Clear error when the vector index is absent ("run --stage 8 first") and when Ollama
  is unreachable (A11).
- Tests (`tests/rag/`):
  - `test_fusion.py` — pure RRF order + weight override + roll-up (A6). No DB.
  - `test_ollama_embed.py` — mocked transport: dimension probe, batch, connection error (A11).
  - `test_stage8_embed.py` — idempotency / `text_hash` skip (A2), governance restriction (C5),
    manifest validates (A1). Neo4j via testcontainers or `--integration` marker; skip when absent.
  - `test_retrievers.py` — vector paraphrase recall (A3), keyword exact-term recall (A4), graph
    leg routes through 0003 gates (A5). Integration-marked.
  - `test_rag_orchestrator.py` — graceful degradation, grounded/cited answer, zero-result honesty
    (A8), Art. 9 notice + Art. 22 lineage (A10), `local-only` egress with a no-network guard (A9).
  - `test_manifest_schema.py` — both manifests validate (A1, A8, A12).

**Exit:** `make test` green; A1–A12 pass; `make embed` then `make rag` run end-to-end against a
local Neo4j 5.13+ and Ollama.

---

**Dependency graph:** A → B, C → D → G; B, C → E → G; A → F → G; D, G → H.

## Risks

- **Neo4j 5.13+ + Ollama availability in CI.** Retrieval and embedding need both live.
  *Mitigation:* fusion is pure and unit-tested without services; embed/retriever tests use
  testcontainers or an `--integration` marker and skip when no instance is present; the embedder is
  tested against a mocked transport.
- **Embedding dimension lock-in (OQ1).** Switching models (e.g. `nomic-embed-text` 768 →
  `bge-m3` 1024) forces an index rebuild + full re-embed. *Mitigation:* pin `nomic-embed-text` in
  v1; manifest records `embedding_model_version`; `ensure_rag_indexes` refuses on a dim mismatch
  with a "rebuild required" error.
- **Hosted-egress regression.** A misconfigured embedding/rerank model could call a hosted API,
  violating G2/N4. *Mitigation:* embedder and reranker are local-only by construction; a no-network
  test asserts `data_egress: local-only`; Stage 8 refuses any non-local embedding endpoint unless an
  explicit opt-in flag is set (spec §9 C2).
- **Graph-leg ranking signal (OQ3).** RRF needs a per-row rank from the graph leg.
  *Mitigation:* honor the generated Cypher `ORDER BY`; expose GDS centrality as a weight only when
  0004 signals are present.
- **Media-vs-creator granularity (OQ4).** Media matches must roll up to the owning Creator.
  *Mitigation:* default roll-up by max; record the chosen strategy in the manifest.
- **Whole-graph vs single-handle scope (OQ5).** RAG is most useful across many creators.
  *Mitigation:* default `--rag` over the whole graph; `--handle` is an optional filter; couples to
  0002 OQ3 cross-handle merging — document.

## Open implementation questions

- **OQ1** Embedding dimension lock-in — pin `nomic-embed-text` (768) in v1 or build
  rebuild-on-mismatch now? *Default:* pin; error on mismatch.
- **OQ2** Reranker host — Ollama-served vs local sentence-transformers behind the `[rag]` extra?
  *Default:* optional extra; reranker off in v1.
- **OQ3** Graph-leg RRF ranking — traversal proximity, GDS centrality (0004), or Cypher
  `ORDER BY`? *Default:* honor `ORDER BY`; weight by centrality when present.
- **OQ4** Media→creator roll-up — max or sum of media scores? *Default:* max.
- **OQ5** Scope — whole graph by default with `--handle` as filter? *Default:* yes (couples to
  0002 OQ3).
