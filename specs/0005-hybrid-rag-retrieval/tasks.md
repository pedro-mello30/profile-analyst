# Tasks 0005 — Hybrid RAG Retrieval (Vector + Graph + Keyword)

From `plan.md`. Track-by-track; each task is independently verifiable. Tasks are
globally numbered `T1…` and grouped under the same tracks as the plan. Acceptance
links (A1–A12) reference `metadata.yml`.

## Track A — Schemas, config, deps, Makefile

- [ ] T1 Write `schemas/09-embed.schema.json` (draft-7): required `handle`, `embedded_at`,
      `embedding_model`, `embedding_model_version`, `dimensions`, `similarity_function`,
      `counts.{embedded,skipped,reembedded}` (Creator + Media), `data_egress` (`local-only`). → A1, A2, A12
- [ ] T2 Write `schemas/10-rag.schema.json` (draft-7): required `question`, `modes_run`,
      `retrievers` (per-mode `k`/`candidates`/`latency_ms`/`error?`), `fusion`
      (`method`/`rrf_k`/`weights`/`fused_candidates`), `rerank` (`enabled`/`model`),
      `generation` (`model`/`latency_ms`), `answer`, `citations[]`, `row_counts`,
      `latency_ms`, `data_egress`, `asked_at`. → A8, A12
- [ ] T3 Extend `tools/validate.py` so `make validate` checks both new schemas. → A12
- [ ] T4 Add env config (spec §11) to `.env` example + CLAUDE.md: `OLLAMA_EMBED_MODEL`,
      `EMBED_DIMENSIONS`, `RAG_VECTOR_K`, `RAG_KEYWORD_K`, `RAG_GRAPH_K`, `RAG_MODES`,
      `RAG_RRF_K`, `RAG_MODE_WEIGHTS`, `RAG_FUSED_TOP_K`, `RAG_RERANK`, `RAG_RERANK_MODEL`,
      `RAG_RERANK_INPUT`, `RAG_RERANK_OUTPUT`.
- [ ] T5 Declare the optional `[rag]` extra (cross-encoder / sentence-transformers) in
      `pyproject.toml`; not installed by default. Reuse 0003's HTTP client for embeddings.
- [ ] T6 Add `make embed`, `make rag`, `make rag-rerank` targets (HANDLE / Q guards).

## Track B — Index migration on the 0002 graph

- [ ] T7 Write `pipeline/rag/indexes.py` — `ensure_rag_indexes(session, dimensions, similarity)`
      running `CREATE VECTOR INDEX creator_embeddings / media_embeddings IF NOT EXISTS` and
      `CREATE FULLTEXT INDEX creator_fulltext / media_fulltext IF NOT EXISTS` (spec §10.1).
      Idempotent. → A1
- [ ] T8 Verify Neo4j ≥ 5.13 at index-creation time; fail with a clear version error otherwise.
- [ ] T9 Refuse index creation when `EMBED_DIMENSIONS` ≠ the model's probed output dimension
      (guards OQ1 dimension lock-in). → A2

## Track C — Ollama embedding client

- [ ] T10 Write `pipeline/llm/ollama_embed.py` — `OllamaEmbedder(host, model)` over
      `/api/embeddings`: `embed(texts)` (single + batch), `get_dimension()` (probe). Reuses
      0003 `OLLAMA_HOST` / `keep_alive`.
- [ ] T11 Raise the 0003 `OllamaError` with a clear "Ollama unreachable at $OLLAMA_HOST" on
      connection failure. → A11
- [ ] T12 Unit-test against a mocked transport: dimension probe, batch shape, connection error. → A11

## Track D — Stage 8 EMBED orchestrator

- [ ] T13 Write `pipeline/stage8_embed.py` — `Stage8EmbedProcessor`; resolve
      `embedding_model`/`embedding_model_version`/`dimensions`; call `ensure_rag_indexes`. → A1
- [ ] T14 Read embeddable text from the graph (Creator: `username`+`display_name`+`bio`+niche
      signals; Media: `caption_text`), restricted to nodes that passed the 0002 governance gate. → C5
- [ ] T15 Idempotency gate: compute `text_hash`; skip nodes whose `text_hash` and
      `embedding_model_version` are unchanged; re-embed the rest. → A2
- [ ] T16 Batch-embed via `OllamaEmbedder`; upsert `embedding`+`embedding_model_version`+`text_hash`
      onto `Creator` (key `user_id`) / `Media` (key `media_id`) — per 0002 §5.1; preserve
      hashtags/@mentions verbatim for full-text. → A1
- [ ] T17 Write `08-embed-manifest.json` atomically (`*.tmp` → `os.replace`); schema-validate;
      record `{embedded,skipped,reembedded}` + `data_egress: local-only`. → A1, A9

## Track E — Retrievers

- [ ] T18 Write `pipeline/rag/retrievers.py` `VectorRetriever.retrieve(embedding, k)` →
      `db.index.vector.queryNodes` over `creator_embeddings`/`media_embeddings` (read session). → A3
- [ ] T19 `KeywordRetriever.retrieve(query, k)` → `db.index.fulltext.queryNodes` over
      `creator_fulltext`/`media_fulltext` (read session); recovers `#ad`/`@handle`/SKU. → A4
- [ ] T20 `GraphRetriever.retrieve(nl_query, k)` → delegate to 0003 `tools/ask.py` NL→Cypher
      (S1–S6 gates + read-only txn); identity via `user_id`, traversal via `HAS_MEDIA`; expose
      0004 GDS signals to ranking when present. → A5
- [ ] T21 Common return shape `{user_id, username, score, source}` across all three retrievers.

## Track F — Fusion + optional rerank

- [ ] T22 Write `pipeline/rag/fusion.py` — `RRFFusion`: `RRF_K=60` (`RAG_RRF_K` overridable),
      `RAG_MODE_WEIGHTS` named constants, media→creator roll-up by max (OQ4), truncate to
      `RAG_FUSED_TOP_K`. Pure / deterministic. → A6
- [ ] T23 Unit-test RRF on fixed per-mode rankings → documented fused order; weight override
      changes order and is recorded. → A6
- [ ] T24 Write `pipeline/rag/rerank.py` — `CrossEncoderReranker`: no-op when `RAG_RERANK=false`
      (default); when on, re-score fused top-K → top-N with local `RAG_RERANK_MODEL` (`[rag]`
      extra); record model in manifest. → A7

## Track G — Orchestrator + generation

- [ ] T25 Write `tools/rag.py` — `HybridRAGOrchestrator.query(question, handle=None)`; embed
      question once; `--handle` optional graph filter, default whole-graph (OQ5).
- [ ] T26 `_run_retrievers` graceful degradation (spec §4.3): single-mode failure → zero
      candidates + logged; all-empty → clear `RAGError`. → A8
- [ ] T27 Fuse → optional rerank → top-N; expand candidates into context block (metrics, niche,
      `Signal`/`Score` with `confidence`/`method`/`art9_risk`, media snippets).
- [ ] T28 Generate once via 0003 `OllamaBackend` (model resolved from 0003 config, never
      hardcoded); grounded-only + cited; zero-result states so without fabrication. → A8
- [ ] T29 Surface Art. 9 notice when any candidate carries `art9_risk:true`; include Art. 22
      signal lineage for any ranking. → A10
- [ ] T30 Write `<ts>-rag.json` atomically; schema-validate; `data_egress: local-only`. → A8, A9

## Track H — CLI wiring + tests

- [ ] T31 Extend `profile_analyst.py`: `--stage 8` (include 8 in `all`), `--rag "<q>"`,
      `--modes`, `--rerank`; clear "run --stage 8 first" when vector index absent, clear
      "Ollama unreachable" when daemon down. → A11
- [ ] T32 `tests/rag/test_fusion.py` — pure RRF order + weight override + roll-up (no DB). → A6
- [ ] T33 `tests/rag/test_ollama_embed.py` — mocked transport: dimension, batch, conn error. → A11
- [ ] T34 `tests/rag/test_stage8_embed.py` — idempotency / `text_hash` skip (A2), governance
      restriction (C5), manifest validates (A1). Neo4j via testcontainers / `--integration`; skip
      when absent.
- [ ] T35 `tests/rag/test_retrievers.py` — vector paraphrase recall (A3), keyword exact-term
      recall (A4), graph leg routes through 0003 gates (A5). Integration-marked.
- [ ] T36 `tests/rag/test_rag_orchestrator.py` — graceful degradation, grounded/cited answer,
      zero-result honesty (A8), Art. 9 notice + Art. 22 lineage (A10), `local-only` with a
      no-network guard (A9).
- [ ] T37 `tests/rag/test_manifest_schema.py` — both manifests validate (A1, A8, A12).
- [ ] T38 Verify `make test` green and `make embed` then `make rag` run end-to-end against a
      local Neo4j 5.13+ and Ollama.

**Total: 38 tasks across 8 tracks (A–H).**

## Out of scope (do not include in this PR)

- GDS computation — Louvain / centrality / link-prediction (spec 0004; 0005 only *reads* its signals).
- A second/dedicated vector store (Qdrant / pgvector) — Neo4j native indexes only (N1).
- Hosted/cloud embeddings or reranking — local-only (N4); deferred only behind explicit opt-in.
- Multi-turn conversational RAG / chat memory (N5).
- Write path from retrieval into the graph or dossier JSON (N3; Stage 8 upserts are the only writes).
