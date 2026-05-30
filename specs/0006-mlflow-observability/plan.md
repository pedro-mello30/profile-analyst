# Plan 0006 — MLflow Observability for the Profile-Analyst Pipeline

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
v1 ships Tracks A–F (config + init + spans + lineage + integration + eval + tests).
Observability is **additive and best-effort** (spec D8): no existing stage behavior changes,
and every helper is a no-op when `OBSERVABILITY_ENABLED=false`.

## Architecture (reference)

```
  ┌─────────────────────────────────────────────────────────────────┐
  │  profile_analyst.py (CLI)  ·  tools/rag.py (0005 RAG entrypoint) │
  │     init_tracing() called once at process start                  │
  └──────────┬──────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │                    observability/  (new package)                 │
  │                                                                   │
  │  config.py     env → Settings(enabled, tracking_uri, experiment) │
  │  tracing.py    init_tracing(): set_uri + set_experiment +         │
  │                openai.autolog()        (no-op when disabled)      │
  │  spans.py      trace(span_type=…) decorator + CHAIN/RETRIEVER/    │
  │                LLM/TOOL constants      (passthrough when disabled) │
  │  lineage.py    log_signal_lineage(score_name, signals, score)     │
  │                → log_params(signal.*) + log_metric  (Art.22)      │
  │  evaluation.py load rag-eval.jsonl → mlflow.genai.evaluate(...)   │
  │  eval/rag-eval.jsonl   versioned eval dataset                     │
  └──────────┬──────────────────────────────────────────────────────┘
             │  decorators / calls applied at integration points
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  CHAIN     influencer_rag            (0005 tools/rag.py)          │
  │  ├─ RETRIEVER hybrid_retrieve        (0005 pipeline/rag)          │
  │  │   ├─ TOOL neo4j_vector_search     (0002 driver)               │
  │  │   └─ TOOL neo4j_graph_traversal   (0002 driver)               │
  │  ├─ TOOL detect_engagement_pods      (0004 GDS, when present)     │
  │  ├─ TOOL calculate_fraud_risk        → log_signal_lineage(...)    │
  │  └─ LLM  chat.completions.create     (0003 Ollama, auto-traced)   │
  └──────────┬──────────────────────────────────────────────────────┘
             │  best-effort export
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  MLflow tracking server (self-hosted)  http://127.0.0.1:5000     │
  │  experiments: influencer-rag-observability · …-eval             │
  │  (OpenTelemetry-exportable — Grafana/Prometheus deferred, N1)    │
  └─────────────────────────────────────────────────────────────────┘
```

A tracking-server outage degrades to no-op and never raises to the caller (spec A5/D8).

## Implementation tracks (dependency-ordered)

### Track A — Package skeleton + config + dependency (foundation)

Create the `observability/` package and its configuration surface.

- `observability/__init__.py` — re-export the public API (`init_tracing`, `trace`,
  span-type constants, `log_signal_lineage`).
- `observability/config.py` — `Settings` loaded from env (spec §8):
  `OBSERVABILITY_ENABLED` (default **false**), `MLFLOW_TRACKING_URI`
  (default `http://127.0.0.1:5000`), `MLFLOW_EXPERIMENT`
  (default `influencer-rag-observability`), `MLFLOW_EXPERIMENT_EVAL`
  (default `influencer-rag-eval`). A single `is_enabled()` helper is the gate every
  other module checks.
- Add `mlflow` to project deps (`pyproject.toml`), behind an optional `[observability]`
  extra so the core install stays lean (mirrors 0001's `[uil]` / 0005's `[rag]` extras).

**Exit:** `from observability.config import Settings, is_enabled` imports cleanly;
`is_enabled()` returns `False` with no env set and `True` when `OBSERVABILITY_ENABLED=true`;
`make validate` still green.

---

### Track B — Tracing init + autolog (depends on A)

`observability/tracing.py`:

```python
def init_tracing() -> None:
    if not is_enabled():
        return                       # D8: no server contact when disabled
    mlflow.set_tracking_uri(settings.tracking_uri)
    mlflow.set_experiment(settings.experiment)
    mlflow.openai.autolog()          # D2: auto-trace Ollama via OpenAI SDK
```

- Idempotent: safe to call more than once (guard against double-`autolog`).
- **Best-effort:** wrap the body so a tracking-server connection error is caught,
  logged at WARNING, and swallowed — never re-raised (spec D8, A5).
- Wire one `init_tracing()` call into the CLI entrypoint and the 0005 RAG entrypoint.

**Exit:** with `OBSERVABILITY_ENABLED=true` and a server up, `init_tracing()` registers
the experiment; with the server **down**, `init_tracing()` returns without raising
(A5); with the flag false, no network call is made (A4).

---

### Track C — Span helpers + taxonomy (depends on A)

`observability/spans.py`:

- Constants `CHAIN`, `RETRIEVER`, `LLM`, `TOOL` (spec D6).
- A `trace(span_type)` decorator that:
  - when enabled, wraps `mlflow.trace(span_type=…)`;
  - when disabled, returns the function unchanged (zero overhead, no import-time
    dependency on a running server).
- A redaction hook (used by Track E) so span inputs/outputs that may carry Art. 9
  content are stripped/hashed before they reach a span payload (spec D9, §9 C2).

**Exit:** decorating a function with `@trace(TOOL)` produces a `TOOL` span when enabled
and is a transparent passthrough when disabled; unit test asserts both the span tree
shape and the no-op path.

---

### Track D — Signal lineage (Art. 22) (depends on A)

`observability/lineage.py`:

```python
def log_signal_lineage(score_name: str, signals: dict[str, float], score: float) -> None:
    if not is_enabled():
        return
    mlflow.log_params({f"signal.{k}": v for k, v in signals.items()})
    mlflow.log_metric(score_name, score)
```

- Best-effort (same swallow-on-error contract as Track B).
- Document the mapping to the existing explainability chain: 0001 `signals[]`,
  0002 `CONTRIBUTED_TO`/`HAS_SIGNAL`, 0003 query manifest (spec §6).

**Exit:** calling `log_signal_lineage("fraud_risk_score", {...}, 0.17)` inside a run
writes one `signal.*` param per signal and one metric (A3), verified against a local
or mocked MLflow client.

---

### Track E — Pipeline integration (depends on B, C, D + specs 0002/0003/0005)

Apply the decorators/calls at the integration points (spec §4.3) **without changing the
behavior** of the wrapped functions:

| Target | Owning spec | Span |
|--------|-------------|------|
| `influencer_rag` (RAG entrypoint) | 0005 `tools/rag.py` | `@trace(CHAIN)` |
| `hybrid_retrieve` | 0005 `pipeline/rag/retrievers.py` | `@trace(RETRIEVER)` |
| Neo4j vector / graph queries | 0002 driver helpers | `@trace(TOOL)` |
| `detect_engagement_pods` (GDS) | 0004 (when present) | `@trace(TOOL)` |
| `calculate_fraud_risk` | scoring | `@trace(TOOL)` + `log_signal_lineage(...)` |
| Ollama call | 0003 | auto (`LLM`, via Track B autolog) |

- Apply the redaction hook (Track C) on any span whose payload could carry Art. 9 text.
- Guard: if 0004/0005 modules are not yet present, integration degrades gracefully
  (decorate what exists; the GDS span is conditional).

**Exit:** with `OBSERVABILITY_ENABLED=true`, a RAG query produces exactly one `CHAIN`
trace containing `RETRIEVER`, ≥1 `TOOL`, and ≥1 `LLM` span (A1); each `LLM` span carries
prompt/response/latency/token-counts/model/params (A2); with the flag false the pipeline
runs identically with zero spans (A4).

---

### Track F — Evaluation harness + eval dataset (depends on E)

- `observability/eval/rag-eval.jsonl` — versioned dataset; each row
  `{"inputs": {"question": …}, "expectations": {"expected_facts": [...]}}` (spec §7).
- `observability/evaluation.py` — loads the dataset and wraps `mlflow.genai.evaluate`
  with the built-in judges `RelevanceToQuery`, `RetrievalGroundedness`,
  `RetrievalSufficiency` (spec D7); logs aggregate metrics to the
  `influencer-rag-eval` experiment.
- New `make eval` target.

**Exit:** `make eval` runs the dataset and prints aggregate
`relevance_to_query/mean`, `retrieval_groundedness/mean`, `retrieval_sufficiency/mean`
(A6). (Live judge execution needs a running Ollama+MLflow; the unit test exercises the
dataset loader and the evaluate-wrapper plumbing with a stub.)

---

### Track G — Tests + docs (depends on A–F)

Write `tests/observability/`:

- `test_config.py` — env parsing; default `enabled=false` (A4 precondition).
- `test_tracing.py` — `init_tracing()` no-ops when disabled; swallows a server-down
  error without raising (A5); idempotent.
- `test_spans.py` — span tree shape when enabled; transparent passthrough when disabled.
- `test_lineage.py` — `signal.*` params + score metric emitted (A3).
- `test_redaction.py` — a fixture carrying a synthetic Art. 9 inference produces **no**
  raw special-category content in the logged payload (A7).
- `test_rag_trace.py` — end-to-end trace shape over a stubbed RAG call: one `CHAIN`
  with `RETRIEVER` + `TOOL` + `LLM` (A1, A2), all against an in-process / mocked MLflow
  client so CI needs no live server.

Docs: a short `observability/README.md` with the §14 local setup
(`pip install 'mlflow' && mlflow server …`) and the env table.

**Exit:** `make test` green; A1–A8 covered; `make validate` green (no new schema, but
metadata stays valid).

---

**Dependency graph:** A → (B, C, D in parallel) → E → F → G.

## Risks

- **MLflow server unavailable in CI.** Tests must not require a live tracking server.
  *Mitigation:* all tests use a mocked/in-process MLflow client or assert the
  disabled-path no-op; the best-effort contract (D8) means a missing server is a
  first-class, tested condition (A5).

- **`mlflow.openai.autolog()` API drift.** MLflow's autolog surface evolves across
  versions. *Mitigation:* pin a known-good `mlflow` minor in the `[observability]`
  extra; isolate the call in `tracing.py` so an upgrade touches one file.

- **Art. 9 leakage into trace payloads.** Prompts/responses can carry special-category
  inferences. *Mitigation:* redaction hook (Track C) applied at every span that could
  carry such text; `test_redaction.py` (A7) is a hard gate.

- **Double instrumentation / overhead when enabled.** Decorating hot paths could add
  latency. *Mitigation:* decorator is a literal passthrough when disabled (default in
  tests/CI); when enabled, spans wrap only the named integration points (§4.3), not
  inner loops.

- **Coupling to not-yet-merged 0004/0005 modules.** The GDS and RAG spans target code
  from other specs. *Mitigation:* Track E decorates what exists and makes the GDS span
  conditional; observability never blocks those specs and degrades gracefully.

- **PII in the MLflow store (retention).** Traces become a new personal-data store.
  *Mitigation:* documented in spec §9 C3; automated erasure of MLflow runs/traces for an
  erased handle is flagged as follow-up (spec OQ2) — not in v1 scope.

## Open implementation questions

- **OQ1 (spec).** Same local model for generation and for the eval judges, or a separate
  judge model? *Default:* same local model in v1; revisit if judge bias shows up.
- **OQ2 (spec).** Wire automated GDPR erasure of MLflow runs/traces into the 0001
  `erase` CLI now, or defer? *Default:* defer (follow-up); document the manual path.
- **OQ3 (spec).** Eval datasets in-repo (`jsonl`) vs MLflow datasets? *Default:* in-repo
  `jsonl` for versioning under git.
- **Mocking strategy.** Use `mlflow`'s in-memory file store (`file:./mlruns` tmp dir) vs
  a `unittest.mock` of the client for trace-shape assertions? *Default:* tmp file store
  for trace-tree tests (real span objects), mock for the disabled-path/no-op tests.
