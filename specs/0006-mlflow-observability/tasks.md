# Tasks 0006 — MLflow Observability

From `plan.md`. Tasks are grouped by the same tracks (A–G) and dependency-ordered.
Each task is independently verifiable and names its acceptance link (A1–A8).
Observability is additive and best-effort: nothing here changes existing stage behavior.

## Track A — Package skeleton + config + dependency

- [ ] **A-1** Create `observability/__init__.py` re-exporting the public API
  (`init_tracing`, `trace`, span-type constants, `log_signal_lineage`).
- [ ] **A-2** Write `observability/config.py`: `Settings` from env
  (`OBSERVABILITY_ENABLED` default **false**, `MLFLOW_TRACKING_URI`,
  `MLFLOW_EXPERIMENT`, `MLFLOW_EXPERIMENT_EVAL`) + `is_enabled()` gate. → A4
- [ ] **A-3** Add `mlflow` to `pyproject.toml` behind an optional `[observability]`
  extra; document the env vars in CLAUDE.md / `.env` example. → A8
- [ ] **A-4** Add `observability/README.md` with the spec §14 local setup
  (`pip install '.[observability]'`, `mlflow server …`) and the env table.

## Track B — Tracing init + autolog

- [ ] **B-1** Write `observability/tracing.py` `init_tracing()`: set tracking URI +
  experiment, call `mlflow.openai.autolog()`; **return immediately** when disabled
  (no server contact). → A4
- [ ] **B-2** Wrap the body best-effort: catch connection/setup errors, log WARNING,
  never re-raise; make the call idempotent (guard double-autolog). → A5
- [ ] **B-3** Wire one `init_tracing()` call into the CLI entrypoint and the 0005 RAG
  entrypoint. → A1

## Track C — Span helpers + taxonomy

- [ ] **C-1** Write `observability/spans.py` with constants
  `CHAIN`, `RETRIEVER`, `LLM`, `TOOL`. → A1
- [ ] **C-2** Implement `trace(span_type)` decorator: wraps `mlflow.trace(span_type=…)`
  when enabled; transparent passthrough when disabled. → A1, A4
- [ ] **C-3** Add a redaction hook used by spans to strip/hash Art. 9-risk content from
  span input/output payloads before logging. → A7

## Track D — Signal lineage (Art. 22)

- [ ] **D-1** Write `observability/lineage.py` `log_signal_lineage(score_name, signals,
  score)`: `log_params({"signal.*": …})` + `log_metric(score_name, score)`; no-op when
  disabled; best-effort on error. → A3
- [ ] **D-2** Document the lineage ↔ explainability mapping (0001 `signals[]`, 0002
  `CONTRIBUTED_TO`/`HAS_SIGNAL`, 0003 query manifest) in the module docstring. → A3

## Track E — Pipeline integration

- [ ] **E-1** Decorate the 0005 RAG entrypoint `influencer_rag` with `@trace(CHAIN)` and
  `hybrid_retrieve` with `@trace(RETRIEVER)`. → A1
- [ ] **E-2** Decorate the 0002 Neo4j vector/graph query helpers with `@trace(TOOL)`;
  conditionally decorate the 0004 GDS `detect_engagement_pods` when present. → A1
- [ ] **E-3** Decorate `calculate_fraud_risk` with `@trace(TOOL)` and call
  `log_signal_lineage(...)` inside it. → A1, A3
- [ ] **E-4** Confirm the Ollama (0003) `LLM` span is captured via the Track B autolog and
  carries prompt/response/latency/tokens/model/params. → A2

## Track F — Evaluation harness + eval dataset

- [ ] **F-1** Create `observability/eval/rag-eval.jsonl` (versioned dataset of
  `{inputs, expectations}` rows per spec §7). → A6
- [ ] **F-2** Write `observability/evaluation.py`: load the dataset, wrap
  `mlflow.genai.evaluate` with `RelevanceToQuery`, `RetrievalGroundedness`,
  `RetrievalSufficiency`; log to the `influencer-rag-eval` experiment. → A6
- [ ] **F-3** Add the `make eval` target that runs F-2 and prints the aggregate means. → A6

## Track G — Tests + docs

- [ ] **G-1** `tests/observability/test_config.py` — env parsing; default
  `enabled=false`. → A4
- [ ] **G-2** `tests/observability/test_tracing.py` — disabled no-op; server-down
  swallowed without raising; idempotent. → A4, A5
- [ ] **G-3** `tests/observability/test_spans.py` — span tree shape when enabled;
  passthrough when disabled (in-process/file-store MLflow client). → A1, A4
- [ ] **G-4** `tests/observability/test_lineage.py` — `signal.*` params + score metric
  emitted. → A3
- [ ] **G-5** `tests/observability/test_redaction.py` — synthetic Art. 9 fixture leaves
  no raw special-category content in the logged payload. → A7
- [ ] **G-6** `tests/observability/test_rag_trace.py` — end-to-end trace over a stubbed
  RAG call: one `CHAIN` with `RETRIEVER` + `TOOL` + `LLM`; assert `LLM` span fields. → A1, A2
- [ ] **G-7** Verify `make validate` and `make test` are green. → A8

## Acceptance coverage map

| Acceptance | Covered by |
|---|---|
| A1 one CHAIN trace w/ RETRIEVER+TOOL+LLM | C-1, C-2, B-3, E-1, E-2, E-3, G-3, G-6 |
| A2 LLM span fields recorded | B-1, E-4, G-6 |
| A3 fraud-risk signal lineage | D-1, D-2, E-3, G-4 |
| A4 disabled = identical, no emission | A-2, B-1, C-2, G-1, G-2, G-3 |
| A5 unreachable server doesn't raise | B-2, G-2 |
| A6 `make eval` prints aggregate means | F-1, F-2, F-3 |
| A7 no raw Art. 9 in trace payloads | C-3, G-5 |
| A8 `make validate` + `make test` pass | A-3, G-7 |

**Total: 26 tasks** across 7 tracks (A–G).

## Out of scope (do not include in this PR)

- Real-time alerting/paging and Grafana/Prometheus/Datadog export (spec N1; future work).
- Multi-host distributed tracing (spec N2).
- Replacing the per-stage JSON artifacts (spec N3 — tracing is additive).
- Mandatory Stage 1–2 ingest/normalize tracing (spec N4).
- Automated GDPR erasure of MLflow runs/traces for an erased handle (spec OQ2; follow-up).
