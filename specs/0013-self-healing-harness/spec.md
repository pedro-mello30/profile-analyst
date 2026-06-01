# Spec 0013 — Self-Healing Harness

> Status: **draft** · Owner: pedro · Depends on: 0001 (Stage 3 contract), 0003 (LLM backend),
> 0006 (MLflow observability), 0010 (never-silently-repair rule)
>
> Adds two concentric self-healing loops around the pipeline, inspired by OpenAI's harness
> engineering post. Verification is the critical point — without a verifier the loop has
> nothing to converge against. The verifiers already exist in every stage; this spec makes
> them the basis of a bounded retry loop (inner) and a periodic diagnosis sweep (outer).

## 1. Context & motivation

The pipeline has strong verifiers at every stage boundary (`jsonschema.validate`, `Art9Scanner`,
`strip_forbidden_features`, FTC status derivation) and idempotent, atomically-written artifacts.
What it lacks is any feedback loop: a single verifier failure kills the run and requires a human
restart. Stage 3 in particular depends on stochastic LLM output — the model sometimes produces
subtly malformed JSON, a wrong value type, or a missing required field. These are formatting
mistakes, not semantic failures, and are exactly the kind of recoverable error that structured
error feedback can fix in-loop.

At the same time, systemic patterns (a feature_id that fails schema 12× across 30 runs, a RAG
eval metric that has drifted 8%) are invisible without aggregation. The outer loop surfaces them
as a human-readable diagnosis report so a single focused prompt/schema fix resolves many future
inner-loop failures.

## 2. Goals / Non-goals

**Goals**
- Inner loop: when Stage 3 LLM output fails schema validation or JSON parsing, feed the
  structured error back to the model and retry within a bounded budget, with full provenance
  logging of every attempt.
- Outer loop: periodically aggregate failure patterns from MLflow traces, diff eval scores
  against a pinned baseline, and emit a diagnosis report that a human can act on.
- Preserve every invariant from 0001 / 0010: `confidence` / `method` / `art9_risk` / `signals`
  are never silently mutated; Art.9 compliance failures are never retried.

**Non-goals**
- Automatic prompt / schema / code modification (the outer loop proposes; humans apply).
- Retrying deterministic stages (1, 2, 6–9). Their failures are data or config bugs.
- Improving model intelligence — this is harness engineering, not model training.

## 3. Architecture

Two concentric loops:

```
┌─────────────────────────────────────────────────────────────┐
│  OUTER LOOP  (make sweep — run periodically / post-batch)   │
│                                                             │
│   MLflow traces + eval dataset                              │
│        │                                                    │
│        ▼                                                    │
│   HealSweep (tools/heal_sweep.py)                           │
│        │  groups failures, diffs vs. baseline               │
│        ▼                                                    │
│   docs/heal-reports/YYYY-MM-DD.md                          │
│   → human reads → PR (prompt / schema / grammar fix)        │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  INNER LOOP  (every Stage 3 run, runtime)            │   │
│  │                                                      │   │
│  │  LLMBackend.extract_features(req)                    │   │
│  │       │                                              │   │
│  │       ▼                                              │   │
│  │  jsonschema.validate / json.JSONDecodeError          │   │
│  │       │ FAIL (schema or decode only)                 │   │
│  │       ▼                                              │   │
│  │  StructuredError → injected as new user turn         │   │
│  │       │ (max 2 retries)                              │   │
│  │       ▼                                              │   │
│  │  Re-invoke backend                                   │   │
│  │       │ PASS / EXHAUSTED                             │   │
│  │       ▼                                              │   │
│  │  Write artifact (with provenance) / HealExhausted   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 4. Inner loop design

### 4.1 New module: `pipeline/llm/retry.py`

```python
@dataclass
class RetryAttempt:
    attempt: int        # 1-based
    error_type: str     # "schema_violation" | "json_decode"
    error_detail: str   # jsonschema path + message, or decode error
    backend: str
    model: str

class HealExhausted(Exception):
    """Raised when all retry attempts are exhausted."""
    attempts: list[RetryAttempt]

def extract_with_retry(
    backend: LLMBackend,
    req: FeatureRequest,
    *,
    max_retries: int = 2,
) -> tuple[FeatureResponse, list[RetryAttempt]]:
    ...
```

### 4.2 Retry context injection

On a verifier failure the structured error is appended as a new `user` turn:

```
"Your previous response failed validation:
  feature_id='niche_category', path='features[2].confidence',
  error='\"0.95\" is not of type number'.
Return only the corrected features array. Do not repeat the explanation."
```

The corrected response is validated again through the same path. If it passes,
execution continues. If not, another attempt is made up to `max_retries`.

### 4.3 Provenance — what changes in the artifact

- `notes` field on each retried feature: `"healed:attempt_1/schema_violation"` appended.
  Original notes are preserved; this is concatenated.
- `FeatureResponse.extra["retry_attempts"]`: the full `list[RetryAttempt]`.
- `confidence`: **unchanged** — it remains the model's own claim. Confidence is an epistemic
  signal about the feature value, not a structural reliability signal about the call.

### 4.4 What is NOT retried

- `Art9Scanner.enforce` failures — these are real compliance risk signals, not formatting errors.
  They propagate immediately, unchanged from today's behavior.
- `OllamaError` (unreachable host) — already handled by the existing fallback mechanism (0010).
  The retry loop does not interact with it.
- Any deterministic stage failure — out of scope (see §2 Non-goals).

### 4.5 Wiring into Stage 3

`pipeline/stage3_features.py` replaces the direct `_extract_llm_features()` call:

```python
# before
llm_features = _extract_llm_features(normalized, anthropic_client=anthropic_client)

# after
llm_features, retry_log = extract_with_retry(backend, req)
# retry_log is passed to the tracer; empty list on clean first-pass
```

Total change: ~10 lines in `stage3_features.py`.

## 5. Outer loop design

### 5.1 New module: `tools/heal_sweep.py`

Three steps, run via `make sweep`:

**Step 1 — Aggregate failures.**
Read the last N MLflow runs (default 30) from the `influencer-features` experiment. Extract
`retry_attempts` artifacts where present. Group by `(error_type, feature_id, schema_path)`.
Produce a ranked failure table.

**Step 2 — Diff eval scores.**
Run `observability/evaluation.py` (or read its last logged metrics) and compare against
`observability/eval/baseline.json`. Flag any metric regression > 5%.

**Step 3 — Emit diagnosis report.**
Write `docs/heal-reports/YYYY-MM-DD.md` with:
- Ranked failure table with example error messages (PII-stripped)
- Eval metric deltas vs. baseline
- Concrete hypothesis per top failure pattern, e.g.:
  *"`niche_category` value fails schema 12×: model returns a free-form string instead of the
  enum. Consider tightening the grammar in `_array_format()` or adding an enum example to
  the Stage 3 prompt."*

HealSweep does not modify any prompt, schema, or code file. All fixes are human-applied.

### 5.2 Baseline pinning

`observability/eval/baseline.json` is a manually maintained snapshot:

```json
{
  "pinned_at": "2026-05-31",
  "metrics": {
    "relevance_to_query/mean": 0.82,
    "retrieval_groundedness/mean": 0.77,
    "retrieval_sufficiency/mean": 0.74
  }
}
```

Updated explicitly after a sweep cycle is reviewed and accepted. Never auto-updated.

## 6. Makefile targets

```makefile
sweep:
    python3 tools/heal_sweep.py --window 30

eval:   ## existing target — extended to also write baseline diff
    OBSERVABILITY_ENABLED=true python3 -m observability.evaluation
```

## 7. Acceptance

Authoritative list in `metadata.yml` `acceptance:`. Summary:

- **A1** — `extract_with_retry()` retries up to 2× on schema/decode errors; `HealExhausted`
  carries full attempt history (unit-tested without live model).
- **A2** — Retried features carry `healed:attempt_N/<error_type>` in `notes`; `confidence`
  is unchanged.
- **A3** — Art.9 failures propagate immediately without entering the retry wrapper.
- **A4** — Retry context contains the specific schema path + message, not a generic prompt.
- **A5** — MLflow run record includes `retry_attempts` artifact when retry occurred.
- **A6** — `make sweep` writes a diagnosis report; does not modify any source file.
- **A7** — `make validate` and `make test` remain green.

## 8. Implementation tracks

**Track 1 — Inner loop** (self-contained, no outer loop dependency)
1. `pipeline/llm/retry.py` — `RetryAttempt`, `HealExhausted`, `extract_with_retry()`
2. `pipeline/stage3_features.py` — wire in `extract_with_retry()`
3. `observability/tracing.py` — log `retry_attempts` when present
4. Tests: `tests/llm/test_retry.py`

**Track 2 — Outer loop** (depends on Track 1 traces existing in MLflow)
1. `observability/eval/baseline.json` — initial snapshot
2. `tools/heal_sweep.py` — aggregation + diff + report
3. `Makefile` — `sweep` target
4. Tests: `tests/observability/test_heal_sweep.py`

## 9. Open questions

See `metadata.yml` `open_questions:` (OQ1–OQ4) for unresolved design decisions around retry
context verbosity, configurable retry budget, sweep time window, and ticket integration.
