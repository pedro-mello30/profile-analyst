# Tasks 0013 — Self-Healing Harness

From `plan.md`. Track A lands first; Track B depends on Track A.

---

## Track A — Inner Retry Loop

- [ ] T1 Add `retry_context: str | None = None` field to `FeatureRequest` in
      `pipeline/llm/base.py`. Both backends must pass it as an additional user turn when present.
- [ ] T2 Create `pipeline/llm/retry.py` with `RetryAttempt` dataclass
      (`attempt`, `error_type`, `error_detail`, `backend`, `model`).
- [ ] T3 Add `HealExhausted(Exception)` to `pipeline/llm/retry.py`; it carries
      `attempts: list[RetryAttempt]` and formats a human-readable message listing all attempt details.
- [ ] T4 Implement `extract_with_retry(backend, req, *, max_retries=2)` in `pipeline/llm/retry.py`:
      retries on `jsonschema.ValidationError` and `json.JSONDecodeError` only; propagates all other
      exceptions immediately; raises `HealExhausted` on exhaustion.
- [ ] T5 Implement `_build_retry_context(error_type, exc)` in `retry.py`: for schema violations,
      include the schema path and error message; for JSON decode errors, include the decode position.
- [ ] T6 Implement `_stamp_provenance(response, attempts)` in `retry.py`: append
      `healed:attempt_N/<error_type>` to each feature's `notes` (preserving existing notes);
      store the serialised attempt list in `response.extra["retry_attempts"]`; never touch `confidence`.
- [ ] T7 Write `tests/llm/test_retry.py` covering:
      - A1: retries up to `max_retries` on `ValidationError`; `HealExhausted` carries full history.
      - A1: succeeds on second attempt; returns `(response, [RetryAttempt(...)])`.
      - A1: `json.JSONDecodeError` also enters the retry loop.
      - A1: clean first pass returns empty attempt list.
      - A2: `confidence` unchanged on retry; `notes` contains `healed:attempt_1/schema_violation`.
      - A2: original `notes` preserved — heal marker is appended.
      - A3: `RuntimeError` (Art.9 stand-in) propagates immediately without entering retry loop.
      - A4: second `FeatureRequest` carries `retry_context` containing the schema path and message.
      - `HealExhausted` message includes all attempt details.
- [ ] T8 Replace `_extract_llm_features()` in `pipeline/stage3_features.py` with
      `extract_with_retry(backend, req)`. Preserve the existing Ollama→Anthropic host-fallback
      by wrapping both the primary and fallback calls with `extract_with_retry`.
- [ ] T9 Remove the now-unused `_extract_llm_features` helper from `stage3_features.py`.
- [ ] T10 Add `log_retry_attempts(attempts: list[dict]) -> None` to `observability/tracing.py`:
       no-op when disabled or list is empty; logs `heal_retry_count` MLflow param and writes
       `retry_attempts.json` artifact; swallows all MLflow errors with a `logger.warning`.
- [ ] T11 Call `log_retry_attempts` from `stage3_features.py` after `extract_with_retry` returns.
- [ ] T12 Add one test to `tests/test_stage3.py` confirming `extract_with_retry` is called by
       `run()` (mock it; assert it was invoked with the right backend and request).
- [ ] T13 Add one test to `tests/observability/test_tracing.py` confirming `log_retry_attempts`
       is a no-op (no exception) when observability is disabled.
- [ ] T14 Run `make test` and confirm green. Run `make validate` and confirm green.

**Exit (Track A):** A1–A5 met; `make test` green; `make validate` green.

---

## Track B — Outer Diagnosis Sweep

- [ ] T15 Create `observability/eval/baseline.json` with zero-valued metrics for
       `relevance_to_query/mean`, `retrieval_groundedness/mean`, `retrieval_sufficiency/mean`;
       include `pinned_at` and `note` fields.
- [ ] T16 Create `tools/heal_sweep.py` with `group_failures(attempts)`:
       groups by `(error_type, path_key)` where `path_key` is extracted from `error_detail`
       (last meaningful segment before the colon); returns `dict[tuple, int]`.
- [ ] T17 Add `diff_baseline(current, baseline, threshold=0.05)` to `heal_sweep.py`:
       returns only metrics that regressed more than `threshold`; skips metrics missing from
       `current`; never raises.
- [ ] T18 Add `render_report(groups, regressions, window)` to `heal_sweep.py`:
       produces a markdown string with a ranked failure table (including a per-row hypothesis),
       a regression section, and a footer; emits a "no failures" message when both inputs are empty.
- [ ] T19 Add `_fetch_mlflow_attempts(window)` to `heal_sweep.py`: reads
       `retry_attempts.json` artifacts from the last `window` MLflow runs; returns `[]` silently
       if MLflow is unavailable or no artifacts exist.
- [ ] T20 Add `main()` CLI to `heal_sweep.py`: `--window 30`, `--out docs/heal-reports/`,
       `--no-eval` flags; creates the output directory if missing; writes `YYYY-MM-DD.md`;
       never modifies any prompt, schema, or source file.
- [ ] T21 Add `sweep` target to `Makefile`:
       `python3 tools/heal_sweep.py --window 30 --no-eval`.
- [ ] T22 Write `tests/observability/test_heal_sweep.py` covering:
       - `group_failures` counts by `(error_type, path_key)`.
       - `group_failures` returns `{}` on empty input.
       - `diff_baseline` flags regressions > threshold.
       - `diff_baseline` ignores improvements and missing current metrics.
       - `render_report` contains the failure table when groups are non-empty.
       - `render_report` contains a regression section when regressions are non-empty.
       - `render_report` emits a "no failures" / "clean" message when both inputs empty.
- [ ] T23 Run `make sweep` and confirm it writes `docs/heal-reports/YYYY-MM-DD.md` without
       modifying any source file.
- [ ] T24 Run `make test` and confirm green (including new `test_heal_sweep.py`).
- [ ] T25 Run `make validate` and confirm green.

**Exit (Track B):** A6–A7 met; `make sweep` writes a report; no source file modified; tests green.

**Total: ~25 tasks across 2 tracks.**

## Out of scope (do not include in these PRs)

- Retrying deterministic stages (1, 2, 6–9) — data or config bugs, not stochastic output.
- Auto-applying prompt / schema / code fixes from the sweep report.
- Configurable `HEAL_MAX_RETRIES` env var (OQ2 — can be added later without breaking the contract).
- GitHub issue / Linear ticket creation from the sweep (OQ4).
- Extending the inner loop to Stage 4 / Stage 5 (no LLM output in those stages yet).
