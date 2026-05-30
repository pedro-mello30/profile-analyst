# Plan 0003 — Ollama Local-LLM Graph Query

Derived from `spec.md`. Single-PR-per-track landing; tracks are dependency-ordered.
This spec adds **(1)** a NL→Cypher query tool over the 0002 graph and **(2)** a pluggable
Stage 3 LLM backend (`anthropic | ollama`). It does **not** modify any 0002 stage and does
**not** add a graph-write path — NL→Cypher is strictly read-only. Follows 0002's per-track,
schema-first discipline.

## Architecture (reference)

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                   profile_analyst.py  (CLI)                        │
  │  --handle <h> --ask "<question>"        --handle <h> --stage 3     │
  └─────────┬───────────────────────────────────────┬─────────────────┘
            │                                         │
  ┌─────────▼───────────────────────────┐  ┌─────────▼───────────────────────┐
  │ tools/ask.py  (NL→Cypher, READ-ONLY) │  │ pipeline/stage3_features.py      │
  │ 1 load+cache graph schema (0002)     │  │  get_llm_backend(LLM_BACKEND)    │
  │ 2 Ollama → {cypher,params,rationale} │  │   ├─ AnthropicBackend (default)  │
  │ 3 cypher_safety.validate (S1–S6)     │  │   └─ OllamaBackend               │
  │ 4 execute_read (neo4j, LIMIT+timeout)│  │  → 03-features.json (same schema)│
  │ 5 Ollama → grounded answer           │  └─────────┬────────────────────────┘
  │ 6 write query manifest               │            │
  └─────────┬───────────────┬────────────┘            │
            │               │                          │
  ┌─────────▼────┐  ┌────────▼─────────┐   ┌───────────▼──────────────┐
  │ tools/       │  │ pipeline/llm/    │   │ pipeline/llm/            │
  │ cypher_safety│  │ ollama_client.py │◄──┤ ollama_backend.py        │
  │ .py (S1–S6)  │  │ (shared seam)    │   │ (validates features schema)│
  └──────────────┘  └──────────────────┘   └──────────────────────────┘
            │
  ┌─────────▼──────────────────────────────────────────────────────────┐
  │ Neo4j 5.x (from 0002)  ·  read-only sessions only                    │
  │ Ollama daemon  http://localhost:11434  (qwen2.5-coder:32b / qwen2.5:14b)│
  └──────────────────────────────────────────────────────────────────────┘
```

Two invariants govern the whole spec: **NL→Cypher never mutates the graph** (read-only by
construction, §6), and **Stage 3 output is backend-independent** (both backends emit JSON that
validates against the unchanged `03-features.schema.json`, §7 C6).

## Implementation tracks (dependency-ordered)

### Track A — Schema, config, deps, Makefile (foundation)

- Write `schemas/08-query.schema.json` (draft-7) for the query manifest: required `question`,
  `cypher`, `params`, `model`, `model_role`, `ollama_host`, `validation` (`passed` + `reasons[]`),
  `row_count`, `latency_ms`, `answer`, `asked_at` (UTC ISO), `read_only`, `data_egress`.
- Extend `tools/validate.py` so `make validate` checks the new schema.
- Add deps to `pyproject.toml` (`requests` or `httpx` for the Ollama HTTP client; no new heavy dep).
- Add env config (spec §8): `LLM_BACKEND`, `OLLAMA_HOST`, `OLLAMA_CYPHER_MODEL`,
  `OLLAMA_FEATURES_MODEL`, `OLLAMA_KEEP_ALIVE`, `ASK_MAX_ROWS`, `ASK_TIMEOUT_MS`, `ASK_FALLBACK`.
- Add `make ask HANDLE=<handle> Q="<question>"` target.

**Exit:** `make validate` green with the new schema; config documented; `make ask` with no args
prints usage.

---

### Track B — LLM backend abstraction + Stage 3 swap (depends on A)

- `pipeline/llm/base.py` — `LLMBackend` ABC (`extract_features(req) -> FeatureResponse`, `name()`)
  and `get_llm_backend(name)` factory (`anthropic` | `ollama`, else `ValueError`).
- `pipeline/llm/anthropic_backend.py` — move the existing Stage 3 Anthropic call behind the ABC;
  no semantic change.
- `pipeline/llm/ollama_client.py` — shared thin HTTP client (`chat`/`generate`, `stream:false`,
  `keep_alive`); raises `OllamaError` with a clear message on unreachable host / non-2xx.
- `pipeline/llm/ollama_backend.py` — Stage 3 via `OllamaClient`; strip code fences, parse JSON,
  validate against `03-features.schema.json`; `method = llm`; never silently repair.
- Refactor `pipeline/stage3_features.py` to select the backend by `LLM_BACKEND` and, on
  `OllamaError`, fall back to Anthropic iff `ASK_FALLBACK=true` (logged); else re-raise. Output
  path/filename/shape unchanged.

**Exit:** `LLM_BACKEND=anthropic --stage 3` is byte-identical to pre-refactor for a fixed input;
`LLM_BACKEND=ollama --stage 3` produces a schema-valid `03-features.json` (A6); Ollama-down with
`ASK_FALLBACK=true` falls back and logs it (A8).

---

### Track C — Cypher safety layer (depends on A)

- `tools/cypher_safety.py` — pure, DB-free, fully unit-testable. Implements spec §6 / §6.1:
  - `_strip_strings_and_comments(cypher)` so S1/S2 scan blanked text (no false reject on a caption
    containing "CREATE"; no keyword smuggled in a comment).
  - S1 write/admin denylist (whole-token, case-insensitive) + **positive CALL allowlist**
    (`db.schema.visualization`, `db.labels`, `db.relationshipTypes`, `db.propertyKeys`).
  - S2 single-statement (reject non-trailing `;`).
  - S4 schema grounding against a `GraphSchema` (labels/rels/properties from §4.1).
  - S5 inject `LIMIT <= ASK_MAX_ROWS` if absent; validate `ASK_MAX_ROWS`/`ASK_TIMEOUT_MS` as
    positive ints.
  - S6 parameterization contract.
  - `validate_and_sanitize_cypher(...) -> CypherValidationResult`; raises
    `QueryRejectedError(reason_code, message, details)` with machine-readable codes
    (`WRITE_KEYWORD`, `MULTI_STATEMENT`, `UNKNOWN_LABEL`, `UNKNOWN_PROPERTY`, `DISALLOWED_CALL`).

**Exit:** unit tests prove every denied keyword/CALL/unknown-identifier is rejected with the right
`reason_code`, a literal `"CREATE"` inside a string is **not** rejected, and a missing `LIMIT` is
injected (A2, A4).

---

### Track D — NL→Cypher tool `tools/ask.py` (depends on B, C; consumes 0002 graph)

- Reuse the 0002 Neo4j driver/config; open **read-only** sessions only.
- `load_graph_schema(driver)` — `CALL db.labels()` / `db.relationshipTypes()` /
  `db.schema.visualization()` → `GraphSchema`; `@lru_cache` per process.
- `build_cypher_generation_messages(schema, question)` — system = schema + S1–S6 rules + few-shot
  from 0002's AQ1–AQ4; request `{cypher, params, rationale}` JSON; `temperature=0`.
- `execute_readonly_query(...)` — `session.execute_read`, pass `ASK_TIMEOUT_MS`, client-side row roof.
- `build_answer_messages(question, rows)` — answer grounded **only** in rows; zero rows → say so;
  surface an Art. 9 notice when rows include `art9_risk` signals (C3).
- `write_manifest(...)` — always written (even on rejection), validates against
  `schemas/08-query.schema.json`; records `model`, `model_role`, `data_egress=local-only`.

**Exit:** `--ask` over a populated 0002 graph returns a grounded answer + schema-valid manifest
(A1); a mutation-seeking question is rejected pre-execution and recorded `validation.passed=false`
(A2); zero-row answer asserts no facts (A5); Art. 9 notice surfaces (A9).

---

### Track E — CLI wiring + tests (depends on B, C, D)

- Extend `profile_analyst.py`: `--ask "<question>"` flag → `tools.ask.ask(handle, question)`.
- Tests (`tests/llm/`, `tests/graph/`):
  - `test_cypher_safety.py` — S1–S6 + reason codes + string/comment stripping (no DB).
  - `test_backends.py` — Anthropic regression parity; Ollama schema validity (mock HTTP); fallback.
  - `test_ask.py` — generation→validation→execution→manifest against a Neo4j test instance
    (testcontainers or `--integration` marker, skip when unavailable); read-only enforcement (A3).
  - `test_manifest_schema.py` — manifest validates (A1, A10).

**Exit:** `make test` green; A1–A10 pass; `make ask HANDLE=sample_creator Q="…"` runs end-to-end
against a local Ollama + Neo4j.

---

**Dependency graph:** A → {B, C} → D → E.

## Risks

- **Ollama / Neo4j availability in CI.** `--ask` needs both a live Ollama and a live Neo4j.
  *Mitigation:* `cypher_safety` and the backends are pure/mockable and unit-tested without either;
  DB+Ollama tests use testcontainers / an `--integration` marker and skip when absent.
- **Denylist bypass.** Regex/keyword filters are historically bypassable.
  *Mitigation:* scan string/comment-stripped text, whole-token match, **positive** CALL allowlist,
  schema grounding, and a read-only transaction as defense-in-depth (S3) — no single gate is trusted alone.
- **Local model output quality.** Small models may emit invalid Cypher or non-JSON.
  *Mitigation:* structured-output request + validation gate; OQ1 bounded one-shot repair; default
  `qwen2.5-coder:32b` for Cypher. Stage 3 validation rejects malformed features rather than accepting them.
- **Stage 3 determinism.** LLM features must pass the schema gate reproducibly.
  *Mitigation:* `temperature=0` + fixed seed (OQ4); validation is the source of truth.

## Open implementation questions

- **OQ1** Cypher repair loop on validation failure. *Default:* one bounded re-prompt, then fail.
- **OQ2** Schema prompt size vs caching. *Default:* send the full (small) static 0002 model.
- **OQ3** Answer model = Cypher model? *Default:* same model; revisit on latency.
- **OQ4** Stage 3 determinism. *Default:* `temperature=0` + fixed seed; confirm chosen models honor it.
