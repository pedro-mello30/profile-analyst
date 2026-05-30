# Spec 0003 — Ollama Local-LLM Graph Query

**Status:** accepted
**Depends on:** `0002-neo4j-graph-persistence` (queries the graph it loads) ·
`0001-social-media-associations-profile` (Stage 3 backend swap)
**Owner:** Pedro Mello
**Created:** 2026-05-30

---

## 1. Problem Statement

Spec 0002 loads the creator dossier into Neo4j and ships a fixed set of hand-written Cypher audit
queries (AQ1–AQ4). Two gaps remain:

- **Ad-hoc graph questions require Cypher.** Brand/analytics teams cannot ask "which creators in my
  niche share more than 40% of their audience and have an undisclosed sponsored post?" without an
  engineer writing Cypher. The 0002 audit queries are static and parameter-only.
- **Stage 3 feature extraction is locked to a hosted API.** Stage 3 (`pipeline/stage3_features.py`)
  calls the Anthropic API (`claude-sonnet-4-6`). For local-first / air-gapped / cost-sensitive runs,
  and for processing data that should not leave the host, there is no on-device alternative.

This spec adds **Ollama as a local LLM provider** in two places:

1. **A natural-language → Cypher query interface** (`tools/ask.py`, CLI `--ask`) that translates a
   plain-language question into a **read-only, validated** Cypher query against the 0002 graph,
   executes it, and returns a grounded answer with full provenance.
2. **A pluggable Stage 3 LLM backend** so feature extraction can run against Ollama instead of the
   Anthropic API, selected by configuration, with identical schema-validated output.

Both use the same local Ollama runtime; neither sends creator data off-host.

## 2. Goals

- G1. **NL→Cypher.** A user asks a question in natural language; a local Ollama model produces a
  single read-only Cypher statement, which is validated, executed, and answered from real graph
  results — never from the model's own world knowledge.
- G2. **Safety by construction.** Generated Cypher that contains any write/mutation or schema clause
  is **rejected before execution**; every query runs inside a read-only transaction. (See §6.)
- G3. **Pluggable Stage 3 backend.** Stage 3 runs against either `anthropic` or `ollama` selected by
  `LLM_BACKEND`, producing output that validates against the **same** `03-features.schema.json` and
  preserves every 0001 invariant (`confidence`, `method`, `art9_risk`, FTC detection).
- G4. **Provenance & auditability.** Every NL→Cypher interaction records the question, the model +
  version, the generated Cypher, bound parameters, row count, and timing into a query manifest —
  extending GDPR Art. 22 "right to explanation" to *which model produced this answer*.
- G5. **Graceful capability awareness.** When Ollama is unreachable or the requested model is not
  pulled, the tooling fails with a clear, actionable error (and Stage 3 can fall back per config).

## 3. Non-Goals

- N1. **No fine-tuning / training** of any model. We use stock Ollama models as-pulled.
- N2. **No write path from the LLM.** The NL→Cypher interface is strictly read-only; it never
  creates, merges, or deletes graph data. Loading remains spec 0002's Stage 7.
- N3. **No GDS algorithms.** Louvain / centrality / link-prediction remain **spec 0004** (renumbered
  from 0002's reservation). The model may *query* graph data but does not compute graph DS.
- N4. **No multi-turn conversational agent / chat memory.** Each `--ask` is a single stateless
  question → query → answer. Conversation state is out of scope.
- N5. **No replacement of the 0002 static audit queries.** AQ1–AQ4 remain the trusted, exact path;
  NL→Cypher is an additive convenience layer.
- N6. **No GPU/hardware provisioning automation.** Hardware sizing is documented (§5.1), not managed.

## 4. Architecture & Integration

```
                         ┌─────────────────────────────┐
 --ask "question"  ─────►│ tools/ask.py (NL→Cypher)     │
                         │  1. fetch graph schema (0002)│
                         │  2. Ollama → Cypher          │──► pipeline/llm/ollama_client.py
                         │  3. validate (read-only)     │        (HTTP localhost:11434)
                         │  4. execute (read txn, neo4j)│
                         │  5. answer + manifest        │──► projects/<h>/queries/<ts>-query.json
                         └─────────────────────────────┘

 --stage 3         ─────► pipeline/stage3_features.py
                            └─ LLMBackend (anthropic | ollama)   ← LLM_BACKEND
                               both emit 03-features.json (same schema)
```

- New package `pipeline/llm/` introducing an `LLMBackend` protocol with two implementations:
  - `AnthropicBackend` — wraps the existing Stage 3 call (default; behavior unchanged).
  - `OllamaBackend` — runs Stage 3 feature extraction against a local Ollama model.
- A **shared** `pipeline/llm/ollama_client.py` (thin HTTP wrapper over `/api/chat`,
  `/api/generate`, `stream:false`, `keep_alive`) is the single seam to Ollama, **reused by both
  `OllamaBackend` and `tools/ask.py`** so there is one place that handles host errors and timeouts.
- New module `tools/ask.py` (the NL→Cypher tool) and CLI flag
  `python3 profile_analyst.py --handle <handle> --ask "<natural-language question>"`.
- New `make` target: `make ask HANDLE=<handle> Q="<question>"`.
- Reuses spec 0002's Neo4j driver and connection config; opens **read-only** sessions only.

### 4.0 Module breakdown

| Module | Responsibility |
|--------|----------------|
| `pipeline/llm/base.py` | `LLMBackend` ABC (`extract_features(req) -> FeatureResponse`, `name()`); `get_llm_backend(name)` factory (`anthropic`\|`ollama`, else `ValueError`) |
| `pipeline/llm/anthropic_backend.py` | Existing Stage 3 Anthropic call refactored behind the ABC; output byte-identical to pre-refactor for a fixed input (regression-tested) |
| `pipeline/llm/ollama_client.py` | Shared `OllamaClient.chat/generate`; raises `OllamaError` (clear "Failed to reach Ollama at …" / HTTP+truncated body) on any non-2xx or unreachable host |
| `pipeline/llm/ollama_backend.py` | Stage 3 via `OllamaClient`; strips code fences, parses JSON, validates against `03-features.schema.json`; **never silently repairs** — validation is the source of truth |
| `tools/ask.py` | Schema load+cache → generate → validate (§6) → read-only execute → answer → manifest; returns non-zero on failure but **always writes a manifest** |

Stage 3 selection lives in `pipeline/stage3_features.py`: read `LLM_BACKEND`, call
`get_llm_backend(...)`, and on an `OllamaError` fall back to Anthropic **iff** `ASK_FALLBACK=true`
(logging the fallback); otherwise re-raise. Output path/filename/shape are unchanged from the
Anthropic-only path so `--stage 3` is a drop-in.

### 4.1 NL→Cypher flow (detail)

1. **Schema grounding.** Read the live graph schema (labels, relationship types, property keys) via
   `CALL db.schema.visualization()` / `db.labels()` / `db.relationshipTypes()`, plus the canonical
   model from spec 0002 §5. This schema is injected into the system prompt so the model can only
   reference real labels/properties. Cached per process (schema is static within a run).
2. **Generation.** Send `system = (schema + rules + few-shot of AQ1–AQ4)` and `user = question` to
   the Ollama model; request a single Cypher statement (structured output: `{ "cypher": ..., "params": {...}, "rationale": ... }`).
3. **Validation** (§6) — reject on any write/admin clause; require it parse and reference only known
   labels/properties.
4. **Execution** in a read-only transaction with a row cap (`LIMIT`/server-side `maxRecords`) and a
   statement timeout.
5. **Answering.** The raw rows + the question are sent back to the model **once** to phrase a
   natural-language answer grounded *only* in the returned rows (no outside facts). Rows are also
   returned verbatim so the answer is checkable.
6. **Manifest.** Persist the full interaction (see §7).

## 5. Model Selection

The model is configured per role, not hard-coded. Recommended Ollama models (from benchmark
research; pick per available VRAM):

### 5.1 NL→Cypher role (`OLLAMA_CYPHER_MODEL`) — favor code/structured-output strength

| Model | Size | Note | VRAM |
|-------|------|------|------|
| **`qwen2.5-coder:32b`** (default) | 32B | Best code/structured generation (~92.7% HumanEval); strongest Cypher | ~20 GB |
| `deepseek-coder:33b` | 33B | Strong multi-language code understanding | ~22 GB |
| `mistral-small` (24B) | 24B | GPT-4-class balance; fits ~12 GB / MacBook | ~12 GB |
| `llama3.1:8b` | 8B | Fast dev/iteration baseline | ~6 GB |
| `codegemma:7b` | 7B | Lightweight local testing | ~6 GB |

### 5.2 Stage 3 feature-extraction role (`OLLAMA_FEATURES_MODEL`) — favor reasoning/NLP + explainability

| Model | Size | Note |
|-------|------|------|
| **`qwen2.5:14b`** (default) | 14B | General reasoning + explainability for signal/sponsored detection |
| `llama3.1:8b` | 8B | Fast signal analysis / NLP |
| `mistral-small` (24B) | 24B | Higher-fidelity feature inference when VRAM allows |

Defaults are overridable via env. Selection rationale and the resolved model are written to the run
manifest (G4) so results are reproducible and comparable across models.

## 6. Query Safety (read-only allowlist + validation)

Generated Cypher passes **all** of these gates before execution, else it is rejected and the
interaction is logged as `rejected`:

- **S1. Write/admin denylist.** Reject (case-insensitive, token-boundary) any of: `CREATE`, `MERGE`,
  `DELETE`, `DETACH`, `SET`, `REMOVE`, `DROP`, `CALL {…} IN TRANSACTIONS`, `LOAD CSV`,
  `CALL apoc.*` write procedures, `CREATE/DROP CONSTRAINT|INDEX`, `FOREACH`, and any
  `dbms.*`/`db.create*` admin procedure. Allow only `MATCH`/`OPTIONAL MATCH`/`WITH`/`WHERE`/
  `RETURN`/`ORDER BY`/`SKIP`/`LIMIT`/`UNWIND`/read-only `CALL`s on the schema/read allowlist.
- **S2. Single statement.** Reject multiple statements (no `;`-separated batches).
- **S3. Read-only transaction.** Execute via `session.execute_read(...)`; the Neo4j user SHOULD also
  be a read-only role (defense in depth). A write attempted at the driver level fails the txn.
- **S4. Schema grounding.** Every label / relationship type / property referenced must exist in the
  live schema (from §4.1 step 1); unknown identifiers → reject (catches hallucinated fields).
- **S5. Resource bounds.** Enforce an automatic `LIMIT` (default 200, `ASK_MAX_ROWS`) and a
  statement timeout (`ASK_TIMEOUT_MS`, default 5000) to prevent runaway traversals.
- **S6. Parameterization.** Literals derived from the user question are bound as Cypher parameters,
  never string-concatenated into the statement.

### 6.1 Implementation contract

The gates live in **one** dedicated module (`tools/cypher_safety.py`) — the single point through
which any model-generated Cypher must pass before execution:

```python
def validate_and_sanitize_cypher(cypher, params, schema, max_rows) -> CypherValidationResult
    # raises QueryRejectedError(reason_code, message, details) on any S1–S2/S4/S6 violation;
    # injects a LIMIT <= max_rows if absent (S5); returns the single sanitized statement + params.
```

- **Scan stripped text, not raw.** S1/S2 keyword and `;` detection run against a copy with **string
  literals and `//`/`/* */` comments blanked out** (`_strip_strings_and_comments`), so a denied
  keyword *inside a string literal* (e.g. a caption containing "CREATE") is not a false reject, and a
  keyword *hidden* in a comment cannot smuggle past the scan. Matching is whole-token, case-insensitive.
- **Positive CALL allowlist (not just denylist).** Any `CALL` whose procedure name is not in
  `{db.schema.visualization, db.labels, db.relationshipTypes, db.propertyKeys}` is rejected — closing
  the gap where an unknown/new write procedure isn't on the denylist.
- **Typed rejection with reason code.** Rejections raise `QueryRejectedError` carrying a
  machine-readable `reason_code` (e.g. `WRITE_KEYWORD`, `MULTI_STATEMENT`, `UNKNOWN_LABEL`,
  `UNKNOWN_PROPERTY`, `DISALLOWED_CALL`); the code + message are recorded in the query manifest's
  `validation.reasons[]` (§7 C1).
- **Bounds are validated config.** `ASK_MAX_ROWS` / `ASK_TIMEOUT_MS` are parsed as positive integers
  (bad values fail fast); the timeout is passed to the read transaction, and the row cap is enforced
  both by the injected `LIMIT` and a client-side roof.

## 7. Provenance & Compliance Invariants

Carried from 0001 §9 / 0002 §7, extended for local LLM use:

- **C1. Query manifest.** Each `--ask` writes `projects/<handle>/queries/<ts>-query.json`, validated
  against `schemas/08-query.schema.json`, containing: `question`, `cypher`, `params`, `model`,
  `model_role`, `ollama_host`, `validation: {passed|rejected, reasons[]}`, `row_count`,
  `latency_ms`, `tokens` (if reported), `answer`, `asked_at` (UTC ISO), `read_only: true`.
- **C2. Art. 22 — model in the explanation.** Because a local model now mediates answers, the
  manifest records *which* model and version produced each result, so an explanation can state the
  full chain: question → model → Cypher → rows → answer.
- **C3. Art. 9 surfacing.** When a query touches `Signal {art9_risk:true}`, the answer MUST surface
  an Art. 9 notice; these results are not silently summarized away.
- **C4. No off-host egress.** When `LLM_BACKEND=ollama`, no creator data is sent to any external API;
  the manifest records `data_egress: local-only`. (Anthropic backend records `data_egress: anthropic-api`.)
- **C5. Grounding guarantee.** The natural-language answer is generated only from returned rows; if
  the query returns zero rows, the answer states that — the model MUST NOT fabricate graph facts.
- **C6. Stage 3 parity.** `OllamaBackend` output validates against the unchanged
  `03-features.schema.json`; `confidence`, `method` (`computed|inferred|llm`), `art9_risk`, and FTC
  `ftc_disclosure_status` are all emitted exactly as the Anthropic backend would. `method` for
  Ollama-derived features is `llm` (the manifest disambiguates the provider).

## 8. Configuration

```
LLM_BACKEND=anthropic            # anthropic | ollama   (Stage 3 backend selector)
OLLAMA_HOST=http://localhost:11434
OLLAMA_CYPHER_MODEL=qwen2.5-coder:32b
OLLAMA_FEATURES_MODEL=qwen2.5:14b
OLLAMA_KEEP_ALIVE=10m            # hold model warm across a run
ASK_MAX_ROWS=200                 # S5 row cap
ASK_TIMEOUT_MS=5000              # S5 statement timeout
ASK_FALLBACK=true                # if ollama unreachable during Stage 3, fall back to anthropic
```

Plus all 0002 Neo4j config (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`).
Assumes a running Ollama daemon (`ollama serve`) with the configured models pulled
(`ollama pull qwen2.5-coder:32b`).

## 9. Acceptance Criteria

- A1. `--ask "list undisclosed sponsored posts for <handle>"` produces a read-only Cypher query,
  executes it against the 0002 graph, returns a grounded answer, and writes a
  `projects/<handle>/queries/<ts>-query.json` that validates against `schemas/08-query.schema.json`.
- A2. **Safety:** a question engineered to elicit a mutation (e.g. "delete all bot users") yields a
  generated query that is **rejected by S1/S4** and never executed; the manifest records
  `validation.passed=false` with reasons.
- A3. **Read-only txn:** even if validation were bypassed, a write Cypher fails because the session
  is `execute_read` (verified by an injected-write unit test).
- A4. **Schema grounding:** a question referencing a non-existent property yields a query rejected by
  S4 (unknown identifier), not a silent empty result.
- A5. **Grounding guarantee:** a question whose query returns zero rows yields an answer that says so
  and asserts no graph facts (C5).
- A6. **Stage 3 parity:** `LLM_BACKEND=ollama python3 profile_analyst.py --handle <h> --stage 3`
  produces a `03-features.json` that validates against `03-features.schema.json` with `confidence`,
  `method`, `art9_risk`, and `ftc_disclosure_status` present.
- A7. **Provenance:** every manifest records the resolved `model`, `model_role`, and
  `data_egress=local-only` when the Ollama backend is used.
- A8. **Capability error:** with Ollama stopped, `--ask` exits non-zero with a clear "Ollama
  unreachable at $OLLAMA_HOST" message; Stage 3 with `ASK_FALLBACK=true` falls back to Anthropic and
  records the fallback in the run log.
- A9. **Art. 9:** a query touching `art9_risk` signals surfaces an Art. 9 notice in the answer (C3).
- A10. `make validate` passes with the new `schemas/08-query.schema.json`.

## 10. Open Questions

- OQ1. **Cypher repair loop.** On a validation/parse failure, do we re-prompt the model once with the
  error to self-correct (bounded retries), or fail fast? Default: one repair attempt, then fail.
- OQ2. **Schema prompt size vs caching.** Large graphs make the injected schema big. Trim to relevant
  labels per question, or always send the full 0002 model? Default: full static 0002 model (small).
- OQ3. **Answer model = Cypher model?** Use one model for both generation and answer-phrasing, or a
  smaller/faster model for phrasing? Default: same model (simpler; revisit on latency).
- OQ4. **Stage 3 determinism.** Set Ollama `temperature=0` + fixed seed for reproducible features;
  confirm chosen models honor seeding well enough for the schema-validation gate.

## 11. Future Work (out of scope here)

- Spec 0004: Neo4j GDS — Louvain (pod detection), centrality (bot detection), link prediction
  (renumbered from 0002's prior 0003 reservation).
- Multi-turn conversational graph agent with memory (N4) once single-shot NL→Cypher is trusted.
- Model benchmark harness (tokens/sec, Cypher-validity rate, answer-grounding rate) across the §5
  candidates, emitting a comparison report.
- Embedding-based semantic search over captions/comments using a local Ollama embedding model.
