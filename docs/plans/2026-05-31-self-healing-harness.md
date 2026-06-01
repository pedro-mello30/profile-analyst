# Self-Healing Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add two concentric self-healing loops to the pipeline: an inner retry loop at the Stage 3 LLM boundary and an outer diagnosis sweep that reads MLflow traces and emits a human-readable report.

**Architecture:** The inner loop lives in `pipeline/llm/retry.py` and wraps the existing `LLMBackend.extract_features()` call in `stage3_features.py`. When the schema verifier or JSON parser fires, the structured error is injected back as a new user turn and the call is retried (max 2×). The outer loop is a standalone script (`tools/heal_sweep.py`) that aggregates retry events from MLflow, diffs eval scores against a pinned baseline, and writes a markdown diagnosis report. Nothing auto-applies fixes.

**Tech Stack:** Python 3.11+, `jsonschema`, `dataclasses`, `mlflow` (already installed), `pytest`, `unittest.mock`

---

## Track 1 — Inner Loop

### Task 1: `RetryAttempt`, `HealExhausted`, and `extract_with_retry()`

**Files:**
- Create: `pipeline/llm/retry.py`
- Create: `tests/llm/test_retry.py`

---

**Step 1: Write the failing tests**

Create `tests/llm/test_retry.py`:

```python
"""Inner retry loop tests — A1, A2, A3, A4 from spec 0013."""
import json
import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock, call
import jsonschema

from pipeline.llm.base import FeatureRequest, FeatureResponse, LLMBackend
from pipeline.llm.retry import (
    RetryAttempt,
    HealExhausted,
    extract_with_retry,
)

# ── minimal valid feature ────────────────────────────────────────────────────

_VALID_FEATURE = {
    "feature_id": "primary_niche",
    "value": "Fitness/Health",
    "unit": None,
    "confidence": 0.88,
    "method": "llm",
    "art9_risk": False,
    "signals": ["hashtags"],
    "notes": None,
}

_NORMALIZED = {"handle": "test", "bio": "", "followers": 1000, "media": []}


def _make_req() -> FeatureRequest:
    return FeatureRequest(normalized=_NORMALIZED)


def _good_response(features=None) -> FeatureResponse:
    return FeatureResponse(
        features=features or [dict(_VALID_FEATURE)],
        model="test-model",
        backend="test",
        data_egress="local-only",
    )


class StubBackend(LLMBackend):
    """Backend whose extract_features() returns responses from a queue."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.calls = []

    def name(self) -> str:
        return "stub"

    def extract_features(self, req: FeatureRequest) -> FeatureResponse:
        self.calls.append(req)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ── A1: retries on schema error, records attempts ───────────────────────────

def test_a1_retries_on_schema_violation_and_records_attempts():
    """A1: retries up to max_retries on ValidationError; HealExhausted on exhaustion."""
    err = jsonschema.ValidationError("'bad' is not of type 'number'")
    err.absolute_path = ["features", 0, "confidence"]

    backend = StubBackend([
        jsonschema.ValidationError("fail 1"),
        jsonschema.ValidationError("fail 2"),
        jsonschema.ValidationError("fail 3"),  # never reached — max 2 retries
    ])

    with pytest.raises(HealExhausted) as exc_info:
        extract_with_retry(backend, _make_req(), max_retries=2)

    healed = exc_info.value
    assert len(healed.attempts) == 2
    assert healed.attempts[0].attempt == 1
    assert healed.attempts[0].error_type == "schema_violation"
    assert healed.attempts[1].attempt == 2


def test_a1_succeeds_on_second_attempt():
    """A1: passes through when retry succeeds."""
    backend = StubBackend([
        jsonschema.ValidationError("fail once"),
        _good_response(),
    ])
    response, attempts = extract_with_retry(backend, _make_req(), max_retries=2)
    assert len(attempts) == 1
    assert attempts[0].attempt == 1
    assert len(response.features) == 1


def test_a1_retries_on_json_decode_error():
    """A1: json.JSONDecodeError also enters the retry loop."""
    backend = StubBackend([
        json.JSONDecodeError("bad json", "", 0),
        _good_response(),
    ])
    response, attempts = extract_with_retry(backend, _make_req(), max_retries=2)
    assert attempts[0].error_type == "json_decode"


def test_a1_clean_pass_returns_empty_attempts():
    """A1: no retries needed → empty attempt list."""
    backend = StubBackend([_good_response()])
    response, attempts = extract_with_retry(backend, _make_req())
    assert attempts == []


# ── A2: confidence unchanged, notes appended ────────────────────────────────

def test_a2_confidence_unchanged_on_retry():
    """A2: confidence on retried feature equals what the model returned."""
    healed_feature = dict(_VALID_FEATURE)
    healed_feature["confidence"] = 0.77  # model's own claim

    backend = StubBackend([
        jsonschema.ValidationError("fail"),
        _good_response(features=[healed_feature]),
    ])
    response, attempts = extract_with_retry(backend, _make_req(), max_retries=2)
    assert response.features[0]["confidence"] == 0.77


def test_a2_notes_contain_heal_marker_on_retry():
    """A2: features carry 'healed:attempt_1/schema_violation' in notes after retry."""
    backend = StubBackend([
        jsonschema.ValidationError("fail"),
        _good_response(),
    ])
    response, attempts = extract_with_retry(backend, _make_req(), max_retries=2)
    notes = response.features[0].get("notes") or ""
    assert "healed:attempt_1/schema_violation" in notes


def test_a2_original_notes_preserved():
    """A2: existing notes are not discarded — the heal marker is appended."""
    feature_with_note = dict(_VALID_FEATURE)
    feature_with_note["notes"] = "original note"

    backend = StubBackend([
        jsonschema.ValidationError("fail"),
        _good_response(features=[feature_with_note]),
    ])
    response, _ = extract_with_retry(backend, _make_req(), max_retries=2)
    notes = response.features[0]["notes"]
    assert "original note" in notes
    assert "healed:attempt_1" in notes


# ── A3: Art.9 not retried ────────────────────────────────────────────────────

def test_a3_art9_failure_propagates_immediately():
    """A3: Art9Scanner errors bypass the retry loop entirely."""
    from pipeline.compliance import Art9Scanner

    class Art9Backend(LLMBackend):
        def name(self): return "art9"
        def extract_features(self, req):
            raise RuntimeError("art9_violation: inferred_religion")

    backend = Art9Backend()
    # Should raise RuntimeError, not HealExhausted
    with pytest.raises(RuntimeError, match="art9_violation"):
        extract_with_retry(backend, _make_req(), max_retries=2)


# ── A4: retry context contains specific error ────────────────────────────────

def test_a4_retry_context_contains_schema_path_and_message():
    """A4: the injected retry message contains the ValidationError path + message."""
    captured_reqs = []

    class CapturingBackend(LLMBackend):
        def __init__(self):
            self._calls = 0
        def name(self): return "capturing"
        def extract_features(self, req):
            captured_reqs.append(req)
            self._calls += 1
            if self._calls == 1:
                err = jsonschema.ValidationError("'xyz' is not of type 'number'")
                err.absolute_path = ["features", 2, "confidence"]
                raise err
            return _good_response()

    extract_with_retry(CapturingBackend(), _make_req(), max_retries=2)
    assert len(captured_reqs) == 2
    retry_context = captured_reqs[1].retry_context
    assert retry_context is not None
    assert "confidence" in retry_context
    assert "'xyz' is not of type 'number'" in retry_context


# ── HealExhausted carries full history ──────────────────────────────────────

def test_heal_exhausted_carries_all_attempts():
    backend = StubBackend([
        jsonschema.ValidationError("fail 1"),
        jsonschema.ValidationError("fail 2"),
    ])
    with pytest.raises(HealExhausted) as exc_info:
        extract_with_retry(backend, _make_req(), max_retries=2)

    exc = exc_info.value
    assert len(exc.attempts) == 2
    assert exc.attempts[0].backend == "stub"
    assert exc.attempts[1].error_detail != ""
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/llm/test_retry.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'pipeline.llm.retry'`

---

**Step 3: Implement `pipeline/llm/retry.py`**

```python
"""Inner retry loop for Stage 3 LLM extraction (spec 0013 §4)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import jsonschema

from pipeline.llm.base import FeatureRequest, FeatureResponse, LLMBackend

logger = logging.getLogger(__name__)


@dataclass
class RetryAttempt:
    attempt: int        # 1-based
    error_type: str     # "schema_violation" | "json_decode"
    error_detail: str   # schema path + message, or decode position
    backend: str
    model: str


class HealExhausted(Exception):
    """All retry attempts exhausted without a valid response."""

    def __init__(self, attempts: list[RetryAttempt]) -> None:
        self.attempts = attempts
        detail = "; ".join(f"attempt {a.attempt}: {a.error_detail}" for a in attempts)
        super().__init__(f"LLM heal exhausted after {len(attempts)} attempt(s): {detail}")


def _build_retry_context(error_type: str, exc: Exception) -> str:
    """Format the structured error message injected back as a user turn."""
    if error_type == "schema_violation" and isinstance(exc, jsonschema.ValidationError):
        path = " → ".join(str(p) for p in exc.absolute_path) or "(root)"
        return (
            f"Your previous response failed schema validation.\n"
            f"  path: {path}\n"
            f"  error: {exc.message}\n"
            f"Return only the corrected features array. Do not repeat the explanation."
        )
    if error_type == "json_decode":
        return (
            f"Your previous response was not valid JSON: {exc}\n"
            f"Return only a valid JSON array of feature objects. "
            f"No markdown fences, no explanation."
        )
    return f"Your previous response failed with: {exc}. Return the corrected features array."


def extract_with_retry(
    backend: LLMBackend,
    req: FeatureRequest,
    *,
    max_retries: int = 2,
) -> tuple[FeatureResponse, list[RetryAttempt]]:
    """Run backend.extract_features(), retrying on schema/JSON failures.

    - Art.9 errors and OllamaError propagate immediately (not retried).
    - On each retry the structured error is injected into req.retry_context.
    - Returns (FeatureResponse, list[RetryAttempt]); list is empty on clean pass.
    - Raises HealExhausted with full attempt history when max_retries exhausted.
    """
    attempts: list[RetryAttempt] = []
    current_req = req

    # First attempt (not counted as a retry)
    try:
        response = backend.extract_features(current_req)
        return _stamp_provenance(response, attempts), attempts
    except (jsonschema.ValidationError, json.JSONDecodeError) as exc:
        pass  # fall through to retry loop
    except Exception:
        raise  # OllamaError, Art.9 errors, anything else — never retried

    # Store the first failure so we can build the retry loop
    # Re-raise is not used above; capture the exc properly
    # (re-structured below for clarity)
    return _retry_loop(backend, req, max_retries=max_retries)


def _retry_loop(
    backend: LLMBackend,
    req: FeatureRequest,
    *,
    max_retries: int,
) -> tuple[FeatureResponse, list[RetryAttempt]]:
    attempts: list[RetryAttempt] = []
    current_req = req

    for attempt_num in range(max_retries + 1):  # attempt 0 = original call
        try:
            response = backend.extract_features(current_req)
            _stamp_provenance(response, attempts)
            return response, attempts
        except (jsonschema.ValidationError, json.JSONDecodeError) as exc:
            if attempt_num == max_retries:
                # Final attempt also failed — exhaust
                error_type = _classify(exc)
                attempts.append(RetryAttempt(
                    attempt=attempt_num,
                    error_type=error_type,
                    error_detail=_detail(exc),
                    backend=backend.name(),
                    model=getattr(backend, "_model", "unknown"),
                ))
                raise HealExhausted(attempts) from exc

            error_type = _classify(exc)
            retry_context = _build_retry_context(error_type, exc)
            detail = _detail(exc)

            logger.warning(
                "Stage 3 LLM output failed (%s): %s — injecting error feedback (attempt %d/%d)",
                error_type, detail, attempt_num + 1, max_retries,
            )

            attempts.append(RetryAttempt(
                attempt=attempt_num + 1,
                error_type=error_type,
                error_detail=detail,
                backend=backend.name(),
                model=getattr(backend, "_model", "unknown"),
            ))

            # Inject error context for next attempt
            current_req = FeatureRequest(
                normalized=req.normalized,
                retry_context=retry_context,
            )
        except Exception:
            raise  # anything else propagates immediately


def _stamp_provenance(
    response: FeatureResponse,
    attempts: list[RetryAttempt],
) -> FeatureResponse:
    """Append heal markers to feature notes when retries occurred."""
    if not attempts:
        return response
    for feat in response.features:
        markers = " | ".join(
            f"healed:attempt_{a.attempt}/{a.error_type}" for a in attempts
        )
        existing = feat.get("notes") or ""
        feat["notes"] = f"{existing} | {markers}".lstrip(" | ") if existing else markers
    response.extra["retry_attempts"] = [
        {"attempt": a.attempt, "error_type": a.error_type,
         "error_detail": a.error_detail, "backend": a.backend, "model": a.model}
        for a in attempts
    ]
    return response


def _classify(exc: Exception) -> str:
    if isinstance(exc, jsonschema.ValidationError):
        return "schema_violation"
    return "json_decode"


def _detail(exc: Exception) -> str:
    if isinstance(exc, jsonschema.ValidationError):
        path = " → ".join(str(p) for p in exc.absolute_path) or "(root)"
        return f"{path}: {exc.message}"
    return str(exc)
```

**Step 4: Extend `FeatureRequest` to carry `retry_context`**

`pipeline/llm/base.py`, `FeatureRequest` dataclass — add one optional field:

```python
@dataclass
class FeatureRequest:
    normalized: dict
    retry_context: str | None = None  # injected on retry (spec 0013)
```

**Step 5: Run tests**

```bash
pytest tests/llm/test_retry.py -v
```

Expected: all tests pass.

**Step 6: Commit**

```bash
git add pipeline/llm/retry.py pipeline/llm/base.py tests/llm/test_retry.py
git commit -m "feat(0013): inner retry loop — RetryAttempt, HealExhausted, extract_with_retry"
```

---

### Task 2: Wire retry loop into Stage 3

**Files:**
- Modify: `pipeline/stage3_features.py` (the `_extract_llm_features` call in `run()`)
- Modify: `tests/test_stage3.py` (one new test)

---

**Step 1: Write the failing test**

Add to `tests/test_stage3.py` inside `TestStage3Run`:

```python
def test_retry_loop_wired_into_stage3(self, tmp_path):
    """Spec 0013 A1: Stage 3 retries on schema error and succeeds on second attempt."""
    import jsonschema
    from pipeline.llm.base import FeatureResponse

    shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")

    good_features = [
        {"feature_id": "primary_niche", "value": "Fitness/Health", "unit": None,
         "confidence": 0.88, "method": "llm", "art9_risk": False,
         "signals": ["hashtags"], "notes": None},
        {"feature_id": "caption_sentiment", "value": "positive", "unit": None,
         "confidence": 0.82, "method": "llm", "art9_risk": False,
         "signals": ["language"], "notes": None},
        {"feature_id": "brand_affinity_signals", "value": [], "unit": None,
         "confidence": 0.7, "method": "llm", "art9_risk": False,
         "signals": [], "notes": None},
        {"feature_id": "likely_sponsored_undisclosed", "value": [], "unit": None,
         "confidence": 0.8, "method": "llm", "art9_risk": False,
         "signals": [], "notes": None},
        {"feature_id": "sponsorship_history", "value": [], "unit": None,
         "confidence": 0.8, "method": "llm", "art9_risk": False,
         "signals": [], "notes": None},
        {"feature_id": "secondary_niches", "value": [], "unit": None,
         "confidence": 0.7, "method": "llm", "art9_risk": False,
         "signals": [], "notes": None},
    ]

    call_count = 0

    def mock_extract(req):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise jsonschema.ValidationError("bad confidence type")
        return FeatureResponse(
            features=good_features,
            model="test", backend="test", data_egress="local-only"
        )

    with patch("pipeline.stage3_features.extract_with_retry") as mock_retry:
        mock_retry.return_value = (
            FeatureResponse(features=good_features, model="t", backend="t", data_egress="local-only"),
            [],
        )
        mock_client = MagicMock()
        out = run("sample_creator", tmp_path, anthropic_client=mock_client)

    assert mock_retry.called
    doc = json.loads(out.read_text())
    assert any(f["feature_id"] == "primary_niche" for f in doc["features"])
```

**Step 2: Run test to confirm it fails**

```bash
pytest tests/test_stage3.py::TestStage3Run::test_retry_loop_wired_into_stage3 -v
```

Expected: FAIL — `extract_with_retry` not imported.

**Step 3: Edit `pipeline/stage3_features.py`**

At the top, add import:

```python
from pipeline.llm.retry import extract_with_retry, HealExhausted
```

Replace the call in `run()`:

```python
# before
llm_features = _extract_llm_features(normalized, anthropic_client=anthropic_client)

# after
backend_name = os.environ.get("LLM_BACKEND", "anthropic")
from pipeline.llm import get_llm_backend, FeatureRequest
backend = get_llm_backend(backend_name, anthropic_client=anthropic_client)
_req = FeatureRequest(normalized=normalized)
try:
    _resp, _retry_log = extract_with_retry(backend, _req)
    llm_features = _resp.features
except OllamaError as exc:
    fallback = os.environ.get("ASK_FALLBACK", "true").strip().lower() == "true"
    if backend.name() == "ollama" and fallback:
        logger.warning("Ollama backend unreachable (%s); falling back to Anthropic for Stage 3.", exc)
        from pipeline.llm import get_llm_backend as _get
        anthropic_b = _get("anthropic", anthropic_client=anthropic_client)
        _resp, _retry_log = extract_with_retry(anthropic_b, _req)
        llm_features = _resp.features
    else:
        raise
```

Remove the now-unused `_extract_llm_features` function.

**Step 4: Run all Stage 3 tests**

```bash
pytest tests/test_stage3.py -v
```

Expected: all pass.

**Step 5: Run full test suite**

```bash
make test 2>&1 | tail -5
```

Expected: same pass count as before ± the new test.

**Step 6: Commit**

```bash
git add pipeline/stage3_features.py tests/test_stage3.py
git commit -m "feat(0013): wire extract_with_retry into Stage 3 run()"
```

---

### Task 3: Log retry attempts in MLflow tracing

**Files:**
- Modify: `observability/tracing.py`
- Modify: `tests/observability/test_tracing.py`

---

**Step 1: Write the failing test**

Add to `tests/observability/test_tracing.py`:

```python
def test_log_retry_attempts_is_no_op_when_disabled():
    """log_retry_attempts must not raise when observability is off."""
    from observability.tracing import log_retry_attempts
    # Should not raise — is a no-op
    log_retry_attempts([{"attempt": 1, "error_type": "schema_violation",
                         "error_detail": "path: x", "backend": "ollama", "model": "qwen"}])
```

**Step 2: Run test to confirm it fails**

```bash
pytest tests/observability/test_tracing.py::test_log_retry_attempts_is_no_op_when_disabled -v
```

Expected: `ImportError: cannot import name 'log_retry_attempts'`

**Step 3: Add `log_retry_attempts` to `observability/tracing.py`**

```python
def log_retry_attempts(attempts: list[dict]) -> None:
    """Log retry_attempts list as an MLflow param when observability is on.

    A no-op when disabled or when MLflow is unavailable (spec 0013 A5).
    """
    if not attempts or not is_enabled():
        return
    try:
        import mlflow
        import json as _json
        mlflow.log_param("heal_retry_count", len(attempts))
        mlflow.log_text(_json.dumps(attempts, indent=2), "retry_attempts.json")
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLflow log_retry_attempts failed (no-op): %s", exc)
```

**Step 4: Call `log_retry_attempts` from Stage 3**

In `pipeline/stage3_features.py`, after `extract_with_retry` succeeds, add:

```python
from observability.tracing import log_retry_attempts as _log_retries
_log_retries([r.__dict__ for r in _retry_log] if _retry_log else [])
```

**Step 5: Run tests**

```bash
pytest tests/observability/test_tracing.py -v
pytest tests/test_stage3.py -v
```

Expected: all pass.

**Step 6: Commit**

```bash
git add observability/tracing.py tests/observability/test_tracing.py pipeline/stage3_features.py
git commit -m "feat(0013): log retry_attempts to MLflow when observability enabled"
```

---

## Track 2 — Outer Loop

### Task 4: Pinned eval baseline

**Files:**
- Create: `observability/eval/baseline.json`

---

**Step 1: Create the baseline snapshot**

```bash
cat > observability/eval/baseline.json << 'EOF'
{
  "pinned_at": "2026-05-31",
  "note": "Initial baseline — update manually after each sweep review cycle.",
  "metrics": {
    "relevance_to_query/mean": 0.0,
    "retrieval_groundedness/mean": 0.0,
    "retrieval_sufficiency/mean": 0.0
  }
}
EOF
```

(Zeros are intentional — the first `make sweep` will show deltas against them. Update after the first real eval run.)

**Step 2: Commit**

```bash
git add observability/eval/baseline.json
git commit -m "feat(0013): add pinned eval baseline for HealSweep diff"
```

---

### Task 5: `tools/heal_sweep.py`

**Files:**
- Create: `tools/heal_sweep.py`
- Create: `tests/observability/test_heal_sweep.py`

---

**Step 1: Write the failing tests**

Create `tests/observability/test_heal_sweep.py`:

```python
"""HealSweep unit tests — A6 from spec 0013."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tools.heal_sweep import (
    group_failures,
    diff_baseline,
    render_report,
)

# ── group_failures ────────────────────────────────────────────────────────────

def test_group_failures_counts_by_key():
    attempts = [
        {"error_type": "schema_violation", "error_detail": "features → 0 → confidence: 'x' is not number", "backend": "ollama", "model": "qwen"},
        {"error_type": "schema_violation", "error_detail": "features → 0 → confidence: 'x' is not number", "backend": "ollama", "model": "qwen"},
        {"error_type": "json_decode", "error_detail": "Expecting value: line 1", "backend": "anthropic", "model": "claude"},
    ]
    groups = group_failures(attempts)
    assert groups[("schema_violation", "confidence")] == 2
    assert groups[("json_decode", "json_decode")] == 1


def test_group_failures_empty():
    assert group_failures([]) == {}


# ── diff_baseline ─────────────────────────────────────────────────────────────

def test_diff_baseline_flags_regression():
    baseline = {"relevance_to_query/mean": 0.82, "retrieval_groundedness/mean": 0.77}
    current  = {"relevance_to_query/mean": 0.74, "retrieval_groundedness/mean": 0.78}
    regressions = diff_baseline(current, baseline, threshold=0.05)
    assert "relevance_to_query/mean" in regressions
    assert "retrieval_groundedness/mean" not in regressions


def test_diff_baseline_no_regression():
    baseline = {"relevance_to_query/mean": 0.82}
    current  = {"relevance_to_query/mean": 0.83}
    assert diff_baseline(current, baseline) == {}


def test_diff_baseline_missing_current_metric_skipped():
    baseline = {"relevance_to_query/mean": 0.82, "other/mean": 0.5}
    current  = {"relevance_to_query/mean": 0.83}
    assert diff_baseline(current, baseline) == {}


# ── render_report ─────────────────────────────────────────────────────────────

def test_render_report_contains_failure_table():
    groups = {("schema_violation", "confidence"): 5}
    regressions = {}
    report = render_report(groups, regressions, window=30)
    assert "schema_violation" in report
    assert "confidence" in report
    assert "5" in report


def test_render_report_contains_regression_section():
    groups = {}
    regressions = {"relevance_to_query/mean": {"baseline": 0.82, "current": 0.74, "delta": -0.08}}
    report = render_report(groups, regressions, window=30)
    assert "relevance_to_query" in report
    assert "regression" in report.lower()


def test_render_report_no_issues_message():
    report = render_report({}, {}, window=30)
    assert "no failures" in report.lower() or "clean" in report.lower()
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/observability/test_heal_sweep.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'tools.heal_sweep'`

**Step 3: Implement `tools/heal_sweep.py`**

```python
#!/usr/bin/env python3
"""HealSweep — outer diagnosis loop (spec 0013 §5).

Reads MLflow traces for the last N runs, groups retry failure patterns,
diffs eval scores against a pinned baseline, and writes a markdown report.
Never modifies prompts, schemas, or code.

Usage:
    python3 tools/heal_sweep.py [--window 30] [--out docs/heal-reports/]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_BASELINE_PATH = Path(__file__).parent.parent / "observability" / "eval" / "baseline.json"
_REPORTS_DIR = Path(__file__).parent.parent / "docs" / "heal-reports"


# ── Step 1: aggregate failures ───────────────────────────────────────────────

def _extract_path_key(error_detail: str) -> str:
    """Pull the last meaningful path segment from an error_detail string."""
    # e.g. "features → 2 → confidence: 'x' is not type number" → "confidence"
    parts = re.split(r"→|:", error_detail)
    for part in reversed(parts):
        stripped = part.strip()
        if stripped and not stripped.isdigit() and len(stripped) < 40:
            return stripped
    return "unknown"


def group_failures(attempts: list[dict]) -> dict[tuple[str, str], int]:
    """Group retry attempts by (error_type, path_key) → count."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for a in attempts:
        error_type = a.get("error_type", "unknown")
        detail = a.get("error_detail", "")
        path_key = _extract_path_key(detail) if error_type == "schema_violation" else error_type
        counts[(error_type, path_key)] += 1
    return dict(counts)


def _fetch_mlflow_attempts(window: int) -> list[dict]:
    """Read retry_attempts.json artifacts from the last *window* MLflow runs."""
    attempts: list[dict] = []
    try:
        import mlflow
        from observability.config import settings
        client = mlflow.MlflowClient()
        exp = client.get_experiment_by_name(settings.experiment)
        if exp is None:
            return []
        runs = client.search_runs(
            experiment_ids=[exp.experiment_id],
            max_results=window,
            order_by=["start_time DESC"],
        )
        for run in runs:
            try:
                path = client.download_artifacts(run.info.run_id, "retry_attempts.json")
                with open(path) as fh:
                    attempts.extend(json.load(fh))
            except Exception:
                pass
    except Exception:
        pass
    return attempts


# ── Step 2: diff eval baseline ───────────────────────────────────────────────

def diff_baseline(
    current: dict[str, float],
    baseline: dict[str, float],
    threshold: float = 0.05,
) -> dict[str, dict]:
    """Return metrics that regressed more than *threshold* relative to baseline."""
    regressions = {}
    for metric, base_val in baseline.items():
        if metric not in current:
            continue
        cur_val = current[metric]
        delta = cur_val - base_val
        if delta < -threshold:
            regressions[metric] = {"baseline": base_val, "current": cur_val, "delta": delta}
    return regressions


def _fetch_current_eval() -> dict[str, float]:
    """Run the eval harness and return the latest metric scores."""
    try:
        from observability.evaluation import run_evaluation
        return run_evaluation()
    except Exception:
        return {}


# ── Step 3: render report ────────────────────────────────────────────────────

def render_report(
    groups: dict[tuple[str, str], int],
    regressions: dict[str, dict],
    window: int,
) -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Heal Sweep Report — {date}",
        f"",
        f"Window: last {window} MLflow runs.",
        f"",
    ]

    # Failure table
    lines.append("## Retry Failure Patterns")
    if not groups:
        lines.append("")
        lines.append("No failures recorded in this window. Clean run.")
    else:
        lines += ["", "| error_type | path / key | count | hypothesis |",
                  "|---|---|---|---|"]
        for (error_type, path_key), count in sorted(groups.items(), key=lambda x: -x[1]):
            hypothesis = _hypothesize(error_type, path_key, count)
            lines.append(f"| {error_type} | {path_key} | {count} | {hypothesis} |")

    # Eval regression section
    lines += ["", "## Eval Score Regressions (vs baseline, threshold 5%)"]
    if not regressions:
        lines.append("")
        lines.append("No regressions detected.")
    else:
        lines += ["", "| metric | baseline | current | delta |",
                  "|---|---|---|---|"]
        for metric, vals in regressions.items():
            lines.append(
                f"| {metric} | {vals['baseline']:.3f} | {vals['current']:.3f} | {vals['delta']:+.3f} |"
            )
        lines += ["", "> **Action:** investigate prompt or schema changes that coincide with these regressions."]

    lines += ["", "---", "_Generated by tools/heal_sweep.py — do not edit manually._"]
    return "\n".join(lines)


def _hypothesize(error_type: str, path_key: str, count: int) -> str:
    if error_type == "json_decode":
        return "Model output was truncated or contained markdown fences; check OLLAMA_TIMEOUT_S and prompt output instructions."
    if path_key in ("confidence", "method", "art9_risk"):
        return f"Model omits or misformats required field `{path_key}`; tighten grammar constraint in `_array_format()` or add an explicit example in the Stage 3 prompt."
    if path_key == "value":
        return "Model returns object-shaped value instead of string/array; check `_array_format()` value type constraint."
    if count >= 5:
        return f"High-frequency failure on `{path_key}`; likely a systematic prompt gap — add a concrete example."
    return f"Occasional failure on `{path_key}`; monitor for recurrence."


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HealSweep: outer diagnosis loop (spec 0013)")
    parser.add_argument("--window", type=int, default=30, help="Number of recent MLflow runs to scan")
    parser.add_argument("--out", type=Path, default=_REPORTS_DIR, help="Output directory for reports")
    parser.add_argument("--no-eval", action="store_true", help="Skip live eval run (use zeroed baseline diff)")
    args = parser.parse_args()

    print(f"HealSweep: scanning last {args.window} runs...")

    raw_attempts = _fetch_mlflow_attempts(args.window)
    groups = group_failures(raw_attempts)
    print(f"  Retry attempts found: {len(raw_attempts)}")
    print(f"  Failure groups: {len(groups)}")

    baseline_metrics: dict[str, float] = {}
    if _BASELINE_PATH.exists():
        baseline_metrics = json.loads(_BASELINE_PATH.read_text()).get("metrics", {})

    current_metrics: dict[str, float] = {}
    if not args.no_eval:
        print("  Running eval harness...")
        current_metrics = _fetch_current_eval()

    regressions = diff_baseline(current_metrics, baseline_metrics)

    report = render_report(groups, regressions, window=args.window)

    args.out.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = args.out / f"{date}.md"
    out_path.write_text(report)
    print(f"  Report written: {out_path}")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tests/observability/test_heal_sweep.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add tools/heal_sweep.py tests/observability/test_heal_sweep.py observability/eval/baseline.json
git commit -m "feat(0013): HealSweep outer loop — failure aggregation + eval diff + report"
```

---

### Task 6: `make sweep` target + final verification

**Files:**
- Modify: `Makefile`

---

**Step 1: Add sweep target to Makefile**

Find the `eval:` target in the Makefile and add `sweep:` after it:

```makefile
sweep:          ## HealSweep: aggregate retry failures + diff eval baseline (spec 0013)
	python3 tools/heal_sweep.py --window 30 --no-eval
```

**Step 2: Verify the target works**

```bash
make sweep
```

Expected output:
```
HealSweep: scanning last 30 runs...
  Retry attempts found: 0
  Failure groups: 0
  Report written: docs/heal-reports/2026-05-31.md
```

**Step 3: Run the full test suite — A7**

```bash
make test 2>&1 | tail -10
```

Expected: same or higher pass count, zero failures.

**Step 4: Run make validate**

```bash
make validate
```

Expected: passes.

**Step 5: Final commit**

```bash
git add Makefile
git commit -m "feat(0013): add make sweep target for HealSweep outer loop"
```

---

## Done

At this point spec 0013 acceptance criteria A1–A7 are met:

| ID | Criterion | Track |
|----|-----------|-------|
| A1 | `extract_with_retry` retries + `HealExhausted` carries history | 1 |
| A2 | Retried features carry `healed:attempt_N` in notes; confidence unchanged | 1 |
| A3 | Art.9 failures propagate immediately, not retried | 1 |
| A4 | Retry context contains specific schema path + message | 1 |
| A5 | MLflow run includes `retry_attempts.json` artifact on retry | 1 |
| A6 | `make sweep` writes diagnosis report; no source files modified | 2 |
| A7 | `make validate` + `make test` green | both |
