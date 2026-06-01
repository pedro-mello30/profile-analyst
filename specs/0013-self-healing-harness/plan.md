# Plan 0013 — Self-Healing Harness

Derived from `spec.md`. Two tracks, dependency-ordered. Track A lands first; Track B depends on
Track A traces existing in MLflow. Both tracks are independently PR-able.

## Architecture (reference)

```
┌─────────────────────────────────────────────────────────────┐
│  OUTER LOOP  (make sweep — Track B, async)                  │
│                                                             │
│   MLflow traces (retry_attempts.json artifacts)             │
│        │                                                    │
│        ▼                                                    │
│   tools/heal_sweep.py                                       │
│        │  group_failures() → diff_baseline() → render()    │
│        ▼                                                    │
│   docs/heal-reports/YYYY-MM-DD.md  ← human acts → PR       │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  INNER LOOP  (Track A, every Stage 3 run)            │   │
│  │                                                      │   │
│  │  pipeline/llm/retry.py                               │   │
│  │       extract_with_retry(backend, req, max=2)        │   │
│  │              │                                       │   │
│  │        FAIL (schema / json_decode only)              │   │
│  │              │                                       │   │
│  │        StructuredError → new user turn               │   │
│  │              │  retry up to max_retries              │   │
│  │        PASS  │  EXHAUSTED → HealExhausted            │   │
│  │              ▼                                       │   │
│  │  FeatureResponse + list[RetryAttempt] (provenance)   │   │
│  │  observability/tracing.log_retry_attempts(...)       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Key invariants (from spec.md §2 + 0010 C6):**
- Art.9 failures are never retried — they propagate immediately.
- `confidence` is never overridden on retry — it stays the model's own claim.
- Every retry is visible in provenance: `notes` field + `FeatureResponse.extra["retry_attempts"]`.
- HealSweep never modifies prompts, schemas, or code — it proposes; humans apply.

## Implementation tracks (dependency-ordered)

### Track A — Inner Retry Loop

Build the retry primitives, wire them into Stage 3, and emit retry traces to MLflow.
All changes are confined to `pipeline/llm/retry.py` (new), a one-field extension to
`pipeline/llm/base.py`, a ~10-line edit to `pipeline/stage3_features.py`, and a new
function in `observability/tracing.py`. Nothing else changes.

**New module:** `pipeline/llm/retry.py`
- `RetryAttempt` dataclass: `attempt` (1-based), `error_type`, `error_detail`, `backend`, `model`.
- `HealExhausted(Exception)`: carries `attempts: list[RetryAttempt]` and a formatted message.
- `extract_with_retry(backend, req, *, max_retries=2)` → `(FeatureResponse, list[RetryAttempt])`:
  - On `jsonschema.ValidationError` or `json.JSONDecodeError`: build a structured feedback message
    (schema path + error message, or decode position), inject it as `req.retry_context`, retry.
  - On any other exception (`OllamaError`, `RuntimeError`, etc.): propagate immediately.
  - On exhaustion: raise `HealExhausted`.
  - On success after retries: stamp each feature's `notes` with `healed:attempt_N/<error_type>`;
    store the attempt list in `FeatureResponse.extra["retry_attempts"]`.

**Base extension:** add `retry_context: str | None = None` to `FeatureRequest` in
`pipeline/llm/base.py`. Both backends pass it as an additional user turn when present.

**Stage 3 wiring:** replace `_extract_llm_features()` in `pipeline/stage3_features.py` with
`extract_with_retry(backend, req)`. The existing Ollama→Anthropic host-fallback wraps the same
call — it's preserved, not replaced.

**Tracing:** add `log_retry_attempts(attempts: list[dict]) -> None` to `observability/tracing.py`.
No-op when observability is disabled. On success, logs `heal_retry_count` param and writes
`retry_attempts.json` artifact to the active MLflow run.

**Exit:** A1–A5 met; `make test` green; `make validate` green.

### Track B — Outer Diagnosis Sweep (depends on Track A)

Build the periodic sweep that reads the MLflow retry traces produced by Track A, groups failure
patterns, diffs eval scores against a pinned baseline, and writes a human-readable diagnosis report.

**New file:** `observability/eval/baseline.json` — pinned metric snapshot. Zeros on creation;
updated manually by the engineer after each sweep review cycle. Never auto-updated.

**New module:** `tools/heal_sweep.py`
- `group_failures(attempts)` → `dict[(error_type, path_key), count]`.
- `diff_baseline(current, baseline, threshold=0.05)` → regressions dict.
- `render_report(groups, regressions, window)` → markdown string.
- `main()` CLI: `--window 30`, `--out docs/heal-reports/`, `--no-eval`. Reads MLflow artifacts,
  calls `observability/evaluation.run_evaluation()` (unless `--no-eval`), writes dated report.
  **Never touches prompts, schemas, or code.**

**Makefile:** new `sweep` target calling `tools/heal_sweep.py --window 30 --no-eval`.

**Exit:** A6–A7 met; `make sweep` writes a report without modifying any source file; `make test` green.

**Dependency graph:** A → B. A and B produce separate PRs.

## Risks

- **Backend compatibility:** `retry_context` injection assumes both Anthropic and Ollama backends
  accept an extra user turn. Both already build `messages` lists from `req.normalized`, so the
  extension is mechanical — but must be verified for each backend in tests.
- **Token cost on retry:** a retry re-sends the full system prompt + user payload + error message.
  With `max_retries=2` this is at most 3× Stage 3 token spend in the failure case. The bound is
  explicit in the spec (D2); no dynamic adjustment is needed.
- **MLflow unavailability:** `log_retry_attempts` must be best-effort (a logging warning, never
  a raised exception), matching the existing pattern in `observability/tracing.py` and `spans.py`.
- **HealSweep with empty MLflow history:** on a fresh install or disabled observability, the sweep
  finds zero artifacts. It must render a clean "no failures" report rather than raising.

## Open implementation questions

See `metadata.yml` `open_questions:` (OQ1–OQ4): retry context verbosity (OQ1), configurable
`HEAL_MAX_RETRIES` env var (OQ2), sweep time-window vs. run-count (OQ3), GitHub/Linear ticket
integration for the sweep output (OQ4).
