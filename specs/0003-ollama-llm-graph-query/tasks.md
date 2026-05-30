# Tasks 0003 — Ollama Local-LLM Graph Query

From `plan.md`. Land track-by-track in dependency order (A → {B, C} → D → E); each task is
independently verifiable.

## Track A — Schema, config, deps, Makefile

- [ ] T1 Write `schemas/08-query.schema.json` (draft-7): required `question`, `cypher`, `params`,
      `model`, `model_role`, `ollama_host`, `validation` (`passed`:bool + `reasons`:array),
      `row_count`, `latency_ms`, `answer`, `asked_at` (UTC ISO 8601), `read_only`:bool,
      `data_egress` (`local-only` | `anthropic-api`).
- [ ] T2 Extend `tools/validate.py` to load and check `08-query.schema.json` under `make validate`.
- [ ] T3 Add HTTP-client dependency to `pyproject.toml` (`requests` or `httpx`); no other new dep.
- [ ] T4 Document the §8 env vars (`LLM_BACKEND`, `OLLAMA_HOST`, `OLLAMA_CYPHER_MODEL`,
      `OLLAMA_FEATURES_MODEL`, `OLLAMA_KEEP_ALIVE`, `ASK_MAX_ROWS`, `ASK_TIMEOUT_MS`, `ASK_FALLBACK`)
      and their defaults.
- [ ] T5 Add `make ask HANDLE=<handle> Q="<question>"` target; print usage when `HANDLE`/`Q` missing.

## Track B — LLM backend abstraction + Stage 3 swap

- [ ] T6 `pipeline/llm/base.py`: `LLMBackend` ABC (`extract_features(req) -> FeatureResponse`,
      `name()`) + `get_llm_backend(name)` factory (`anthropic`|`ollama`, else `ValueError`).
- [ ] T7 `pipeline/llm/anthropic_backend.py`: move the existing Stage 3 Anthropic call behind the
      ABC with no semantic change; shared `_build_messages` / `_parse_structured_output` helpers.
- [ ] T8 `pipeline/llm/ollama_client.py`: shared `OllamaClient.chat/generate` (`stream:false`,
      `keep_alive`); raise `OllamaError` (clear "Failed to reach Ollama at …" / HTTP+truncated body).
- [ ] T9 `pipeline/llm/ollama_backend.py`: Stage 3 via `OllamaClient`; strip code fences, parse JSON,
      validate against `03-features.schema.json`; `method=llm`; raise (never silently repair) on
      unreachable / invalid JSON / schema failure.
- [ ] T10 Refactor `pipeline/stage3_features.py`: select backend by `LLM_BACKEND`; on `OllamaError`
      fall back to Anthropic iff `ASK_FALLBACK=true` (log it), else re-raise; output path/shape unchanged.

## Track C — Cypher safety layer

- [ ] T11 `tools/cypher_safety.py`: `GraphSchema`, `CypherValidationResult`, `QueryRejectedError`
      (with `reason_code`, `message`, `details`).
- [ ] T12 `_strip_strings_and_comments(cypher)` — blank `'...'`/`"..."` literals and `//`, `/* */`
      comments before scanning.
- [ ] T13 S1 write/admin denylist (whole-token, case-insensitive) + S2 single-statement check on the
      stripped text; reject `CALL {…} IN TRANSACTIONS`, `LOAD CSV`, `(CREATE|DROP) (CONSTRAINT|INDEX)`,
      `FOREACH`, `dbms.*`, `db.create*`, APOC write prefixes.
- [ ] T14 Positive CALL allowlist `{db.schema.visualization, db.labels, db.relationshipTypes,
      db.propertyKeys}`; any other `CALL` → `DISALLOWED_CALL`.
- [ ] T15 S4 schema grounding: every referenced label/rel/property must exist in `GraphSchema`
      (`UNKNOWN_LABEL`/`UNKNOWN_PROPERTY`).
- [ ] T16 S5 inject `LIMIT <= ASK_MAX_ROWS` if absent; validate `ASK_MAX_ROWS`/`ASK_TIMEOUT_MS` as
      positive ints (fail fast on bad values). S6 parameterization contract.
- [ ] T17 `validate_and_sanitize_cypher(cypher, params, schema, max_rows) -> CypherValidationResult`
      tying S1–S6 together.

## Track D — NL→Cypher tool `tools/ask.py`

- [ ] T18 `load_graph_schema(driver)` via `CALL db.labels()` / `db.relationshipTypes()` /
      `db.schema.visualization()` → `GraphSchema`; `@lru_cache` per process; read-only session.
- [ ] T19 `build_cypher_generation_messages(schema, question)` — system = schema + S1–S6 rules +
      few-shot from 0002 AQ1–AQ4; request `{cypher, params, rationale}` JSON; `temperature=0`.
- [ ] T20 `execute_readonly_query(driver, cypher, params, max_rows, timeout_ms)` via
      `session.execute_read`, passing `ASK_TIMEOUT_MS` and a client-side row roof.
- [ ] T21 `build_answer_messages` + `generate_answer_text` — grounded only in rows; zero rows → say
      so; surface an Art. 9 notice when rows contain `art9_risk` signals (C3, C5).
- [ ] T22 `write_manifest(...)` → `projects/<handle>/queries/<ts>-query.json`, always written (incl.
      rejection), validated against `08-query.schema.json`; records `model`, `model_role`,
      `data_egress=local-only`, `validation.reasons[]`.
- [ ] T23 `ask(handle, question)` orchestrator: generate → validate (Track C) → execute → answer →
      manifest; non-zero exit on failure; clear "Ollama unreachable" error when the daemon is down.

## Track E — CLI wiring + tests

- [ ] T24 Extend `profile_analyst.py`: add `--ask "<question>"` → `tools.ask.ask(args.handle, args.ask)`.
- [ ] T25 `tests/llm/test_cypher_safety.py` — S1–S6, reason codes, string/comment stripping, LIMIT
      injection (no DB) — covers A2, A4.
- [ ] T26 `tests/llm/test_backends.py` — Anthropic regression parity; Ollama schema validity (mock
      HTTP); `ASK_FALLBACK` fallback — covers A6, A8.
- [ ] T27 `tests/graph/test_ask.py` — generation→validation→execution→manifest against a Neo4j test
      instance (testcontainers / `--integration`, skip when absent); read-only enforcement — covers
      A1, A3, A5, A7, A9.
- [ ] T28 `tests/test_manifest_schema.py` — query manifest validates against `08-query.schema.json`
      (A1, A10).

**Total: ~28 tasks** across 5 tracks.

## Out of scope (do not include in this PR)

- Neo4j GDS algorithms — Louvain / centrality / link prediction (spec 0004).
- Multi-turn conversational graph agent / chat memory (deferred until single-shot NL→Cypher is trusted).
- Model fine-tuning or training (stock Ollama models only).
- A graph-write path from the LLM (NL→Cypher is read-only by construction).
- Model benchmark harness across the §5 candidates (future work).
