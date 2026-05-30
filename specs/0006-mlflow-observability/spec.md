# Spec 0004 — MLflow Observability for the Profile-Analyst Pipeline

**Status:** draft
**Depends on:** [0002 Neo4j Graph Persistence], [0003 Ollama LLM Graph Query]
**Owner:** Pedro Mello
**Source of truth:** this document. Read before implementing anything in `observability/`.

---

## 1. Purpose

Add production-grade observability to the influencer-marketing pipeline so that every
LLM call, every Neo4j graph query, every hybrid-retrieval step, and every fraud-risk
computation is **traced, measurable, and auditable**.

Observability is not a nice-to-have for this system: GDPR Art. 22 requires that any score
used to make decisions affecting creators (campaign selection, fraud flagging) be
**explainable** and **auditable**. MLflow tracing gives us the durable signal-lineage
record that satisfies that obligation, in addition to ordinary engineering value
(latency, cost, debugging, regression detection).

The chosen tool is **MLflow** (self-hosted, open-source). It is OpenTelemetry-compatible,
so traces can later be exported to an existing stack (Grafana/Prometheus/Datadog) without
vendor lock-in.

## 2. Background

The pipeline already produces a dossier from an Instagram handle (spec 0001), persists
the associations graph in Neo4j (spec 0002), and answers natural-language graph queries
through a local Ollama LLM in a hybrid (vector + graph) RAG loop (spec 0003).

Today these steps are opaque: when a creator scores high or low for fraud risk, or when a
RAG answer looks wrong, there is no structured record of *which signals*, *which retrieved
context*, and *which model parameters* produced the result. That blocks both debugging and
GDPR audit.

## 3. Goals

- **G1** — Trace every Ollama LLM call automatically (prompt, response, latency, token
  usage, model, parameters, exceptions).
- **G2** — Trace every Neo4j graph query and hybrid-retrieval step with custom spans,
  nested under the owning RAG request.
- **G3** — Capture **signal lineage** for every fraud-risk / decision score as MLflow
  params + metrics, so the audit trail answers "which signals drove this score?".
- **G4** — Provide a repeatable **evaluation** harness (relevance, groundedness,
  sufficiency) to quantify RAG quality before changes ship.
- **G5** — Provide **experiment tracking** to A/B compare models, prompts, and retrieval
  strategies.
- **G6** — Remain fully self-hosted and OpenTelemetry-exportable (no SaaS dependency).

## 4. Non-Goals / Deferred

- **N1** — Real-time alerting/paging (thresholds in §10 are documented, but wiring to
  Grafana/Prometheus/PagerDuty is deferred to a later spec).
- **N2** — Distributed tracing across multiple hosts; v1 assumes single-host deployment.
- **N3** — Replacing the existing per-stage JSON artifacts. MLflow traces are *additive*;
  the canonical pipeline artifacts (`01-raw.json` … `06-dossier.json`) remain unchanged.
- **N4** — Tracing Stage 1–2 ingest/normalize is optional in v1 (low LLM/graph content);
  required tracing starts at Stage 3 (features) and the RAG query path.

## 5. Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | Use MLflow, self-hosted, as the observability backend. | Open-source, free, OTel-compatible, built-in LLM tracing + eval + experiment tracking. |
| D2 | Enable `mlflow.openai.autolog()` for the Ollama path. | Ollama exposes an OpenAI-compatible API; one line auto-traces all LLM calls with zero code change at call sites. |
| D3 | Wrap custom steps with `@mlflow.trace(span_type=...)` decorators. | Neo4j queries, hybrid retrieval, and GDS fraud algorithms need manual spans nested under the request. |
| D4 | Tracking URI, experiment name, and enable/disable are config-driven (env vars). | Observability must be switchable off in tests/CI and pointable at any server. |
| D5 | Fraud/decision scores log their input signals via `mlflow.log_params` + the score via `mlflow.log_metric`. | Direct mapping to GDPR Art. 22 explainability requirement; durable, queryable lineage. |
| D6 | Span type taxonomy is fixed: `CHAIN`, `RETRIEVER`, `LLM`, `TOOL`. | Stable, inspectable trace tree; consistent with MLflow GenAI conventions. |
| D7 | Evaluation uses MLflow built-in judges (`RelevanceToQuery`, `RetrievalGroundedness`, `RetrievalSufficiency`). | No custom judge maintenance; standard, comparable metrics. |
| D8 | Observability failures MUST NOT break the pipeline. | Tracing is best-effort; a tracking-server outage degrades to no-op, never an exception to the user. |
| D9 | No raw special-category (Art. 9) content is written into trace payloads. | Traces are a new data store; they inherit the project's Art. 9 minimization rules (see §9). |

## 6. Architecture

```
observability/
├── __init__.py
├── config.py          # reads env, builds tracking URI, enable/disable flag
├── tracing.py         # init_tracing(): set_tracking_uri, set_experiment, autolog
├── spans.py           # @trace helpers + span_type constants (CHAIN/RETRIEVER/LLM/TOOL)
├── lineage.py         # log_signal_lineage(score_name, signals: dict, score: float)
└── evaluation.py      # eval dataset loader + mlflow.genai.evaluate wrapper
```

### 6.1 Initialization

A single `init_tracing()` call, made once at process start (CLI entrypoint and the RAG
service entrypoint), performs:

```python
mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
mlflow.set_experiment(settings.MLFLOW_EXPERIMENT)
if settings.OBSERVABILITY_ENABLED:
    mlflow.openai.autolog()   # D2 — auto-trace Ollama via OpenAI SDK
```

If `OBSERVABILITY_ENABLED` is false, all helpers in `spans.py`/`lineage.py` become no-ops
(D4, D8).

### 6.2 Trace tree (target shape)

```
influencer_rag (CHAIN)
├── hybrid_retrieve (RETRIEVER)
│   ├── neo4j_vector_search  (TOOL)
│   └── neo4j_graph_traversal (TOOL)
├── detect_engagement_pods (TOOL)        # GDS Louvain, logs num_pods_detected
├── calculate_fraud_risk (TOOL)          # logs signals (params) + fraud_risk (metric)
└── chat.completions.create (LLM)        # auto-traced: prompt/response/latency/tokens
```

### 6.3 Integration points (where spans are added)

| Component (from prior specs) | Span | span_type |
|------------------------------|------|-----------|
| RAG entrypoint (spec 0003) | `influencer_rag` | `CHAIN` |
| Hybrid retrieval (spec 0003) | `hybrid_retrieve` | `RETRIEVER` |
| Neo4j vector / graph queries (spec 0002) | per-query | `TOOL` |
| GDS pod / community detection (spec 0002) | `detect_engagement_pods` | `TOOL` |
| Fraud-risk scoring | `calculate_fraud_risk` | `TOOL` |
| Ollama call (spec 0003) | auto | `LLM` (autolog) |
| Stage 3 features (Claude path, spec 0001) | `stage3_features` | `CHAIN` (optional v1) |

## 7. Signal Lineage (GDPR Art. 22)

Every score that can affect a creator MUST emit lineage. `lineage.py` provides:

```python
def log_signal_lineage(score_name: str, signals: dict[str, float], score: float) -> None:
    """Record which signals drove a decision score, for GDPR Art. 22 audit."""
    if not enabled: return
    mlflow.log_params({f"signal.{k}": v for k, v in signals.items()})
    mlflow.log_metric(score_name, score)
```

This makes the trace answer, for any flagged creator: *which signals*, *what weights*,
*what final score*, *which model/params produced the answer*. Combined with the existing
`signals: []` explainability block in `06-dossier.json` (CLAUDE.md invariant), this closes
the audit loop: the dossier states the signals, the trace proves how they were combined.

### Example lineage record (`fraud_risk`)

```json
{
  "run_id": "a1b2c3",
  "score_name": "fraud_risk_score",
  "score": 0.17,
  "params": {
    "signal.follower_growth_anomaly": 0.10,
    "signal.comment_quality_score": 0.82,
    "signal.engagement_rate": 0.041
  },
  "trace_id": "tr-0099"
}
```

## 8. Evaluation Harness

`evaluation.py` wraps `mlflow.genai.evaluate` over a versioned eval dataset stored at
`observability/eval/rag-eval.jsonl`. Each row:

```json
{
  "inputs": {"question": "Find fitness creators with fraud risk < 0.2"},
  "expectations": {"expected_facts": ["fitness", "fraud risk", "< 0.2", "engagement_rate"]}
}
```

Scorers (D7): `RelevanceToQuery`, `RetrievalGroundedness`, `RetrievalSufficiency`.
Run via `make eval` (new target). Aggregate metrics are logged to the
`influencer-rag-eval` experiment so quality is tracked over time.

## 9. Compliance

- **Art. 22 (explainability):** satisfied by §7 signal lineage. Required for every
  decision-affecting score.
- **Art. 9 (special-category minimization):** trace payloads MUST NOT contain raw
  special-category content. Prompts/responses that could carry Art. 9 inferences are
  redacted or hashed before logging; only the `art9_risk: true` flag and the derived
  score are traced (D9). Reuses the redaction rules from spec 0001 §9.
- **Retention:** trace and run data inherit the project's data-retention window; the
  MLflow store is treated as personal-data-bearing and is subject to the same erasure
  (right-to-be-forgotten) path as pipeline artifacts. *(Implementation of automated
  erasure on the MLflow store is flagged as a follow-up, see N1-adjacent.)*
- **Self-hosting:** no creator data leaves the local infrastructure (D1, G6).

## 10. Key Metrics & Thresholds (documented; alerting deferred — N1)

| Metric | Meaning | Alert threshold |
|--------|---------|-----------------|
| LLM latency (p95) | response time per query | > 2s |
| Tokens per query | cost proxy | > 1000 tokens |
| Retrieval sufficiency (mean) | context adequacy | < 0.7 |
| Groundedness (mean) | hallucination rate | < 0.8 |
| Neo4j query latency | graph traversal speed | > 500ms |
| Fraud detection precision | pod/bot detection quality | < 0.9 |

## 11. Configuration (env vars)

```
OBSERVABILITY_ENABLED=true              # master switch (false in CI/tests)
MLFLOW_TRACKING_URI=http://127.0.0.1:5000
MLFLOW_EXPERIMENT=influencer-rag-observability
MLFLOW_EXPERIMENT_EVAL=influencer-rag-eval
```

Default for `OBSERVABILITY_ENABLED` in test runs is `false` (D4, D8).

## 12. Acceptance Criteria (testable)

- **A1** — With `OBSERVABILITY_ENABLED=true`, running a RAG query produces exactly one
  `CHAIN` trace whose tree contains `RETRIEVER`, ≥1 `TOOL`, and ≥1 `LLM` span.
- **A2** — Each `LLM` span records prompt, response, latency, input/output token counts,
  model name, and parameters (temperature, max_tokens).
- **A3** — `calculate_fraud_risk` produces a run where every input signal appears as a
  `signal.*` param and the final score appears as a metric.
- **A4** — With `OBSERVABILITY_ENABLED=false`, the pipeline runs identically with no calls
  to the tracking server, and no span/param/metric is emitted.
- **A5** — A tracking-server outage (unreachable URI) does not raise to the caller; the
  pipeline completes and returns the same result (D8).
- **A6** — `make eval` runs the eval dataset and prints aggregate
  `relevance_to_query/mean`, `retrieval_groundedness/mean`, `retrieval_sufficiency/mean`.
- **A7** — No raw Art. 9 content appears in any logged trace payload (verified by a
  redaction unit test on a fixture containing a synthetic special-category inference).
- **A8** — `make validate` passes (schemas + metadata.yml) and `make test` passes with the
  new observability unit tests.

## 13. Out of Scope

See §4 (N1–N4). Specifically: alerting/paging wiring, multi-host distributed tracing,
automated GDPR erasure on the MLflow store, and replacement of existing JSON artifacts.

## 14. Setup Reference

Local quick start:

```bash
pip install mlflow openai neo4j sentence-transformers
mlflow server --host 127.0.0.1 --port 5000   # UI at http://127.0.0.1:5000
```

Production (Docker Compose with PostgreSQL + MinIO) is documented in `plan.md`.
