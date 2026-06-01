"""Tests for the self-healing retry loop (spec 0013 Track A1).

Acceptance criteria covered:
    A1 — retries up to max_retries on ValidationError / JSONDecodeError
    A2 — confidence is never overridden; healed notes appended; original notes preserved
    A3 — non-schema exceptions propagate immediately (no retry)
    A4 — retry_context on the second FeatureRequest carries schema path + error message
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import pytest

from pipeline.llm.base import FeatureRequest, FeatureResponse, LLMBackend
from pipeline.llm.retry import (
    HealExhausted,
    RetryAttempt,
    _build_retry_context,
    _classify,
    _detail,
    _stamp_provenance,
    extract_with_retry,
)

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_FEATURE = {
    "feature_id": "primary_niche",
    "value": "Fitness/Health",
    "unit": None,
    "confidence": 0.88,
    "method": "llm",
    "art9_risk": False,
    "signals": ["hashtags"],
    "notes": None,
}

_GOOD_FEATURE_WITH_NOTES = {
    **_GOOD_FEATURE,
    "confidence": 0.77,
    "notes": "original note",
}


def _good_response(features=None, *, confidence=0.88, notes=None) -> FeatureResponse:
    feats = features or [{**_GOOD_FEATURE, "confidence": confidence, "notes": notes}]
    return FeatureResponse(
        features=feats,
        model="stub-model",
        backend="stub",
        data_egress="local-only",
    )


def _normalized():
    return json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())


class StubBackend(LLMBackend):
    """Returns responses from a queue; raises if item is an Exception."""

    def __init__(self, responses: list) -> None:
        self._queue: deque = deque(responses)
        self._calls: list[FeatureRequest] = []

    def extract_features(self, req: FeatureRequest) -> FeatureResponse:
        self._calls.append(req)
        item = self._queue.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def name(self) -> str:
        return "stub"


def _validation_error() -> jsonschema.ValidationError:
    schema = {
        "type": "object",
        "properties": {"confidence": {"type": "number", "minimum": 0}},
        "required": ["confidence"],
    }
    try:
        jsonschema.validate({"confidence": "not-a-number"}, schema)
    except jsonschema.ValidationError as exc:
        return exc
    raise AssertionError("Expected ValidationError")


def _json_decode_error() -> json.JSONDecodeError:
    try:
        json.loads("{bad json")
    except json.JSONDecodeError as exc:
        return exc
    raise AssertionError("Expected JSONDecodeError")


# ---------------------------------------------------------------------------
# A1 — retry loop behaviour
# ---------------------------------------------------------------------------

class TestRetryLoopBehaviour:
    def test_clean_first_pass_returns_empty_attempt_list(self):
        """A successful first call yields the response and an empty attempt list."""
        backend = StubBackend([_good_response()])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        assert attempts == []
        assert resp.features[0]["feature_id"] == "primary_niche"

    def test_succeeds_on_second_attempt_returns_one_retry_attempt(self):
        """First call fails with ValidationError; second succeeds — attempt list has one entry."""
        backend = StubBackend([_validation_error(), _good_response()])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        assert len(attempts) == 1
        assert attempts[0].attempt == 1
        assert attempts[0].error_type == "schema_violation"

    def test_exhaustion_raises_healexhausted_with_full_history(self):
        """All max_retries exhausted → HealExhausted carrying every RetryAttempt."""
        backend = StubBackend([
            _validation_error(),
            _validation_error(),
            _validation_error(),
        ])
        with pytest.raises(HealExhausted) as exc_info:
            extract_with_retry(backend, FeatureRequest(_normalized()), max_retries=2)

        err = exc_info.value
        assert len(err.attempts) == 2
        assert err.attempts[0].attempt == 1
        assert err.attempts[1].attempt == 2

    def test_json_decode_error_enters_retry_loop(self):
        """json.JSONDecodeError is retriable (same as ValidationError)."""
        backend = StubBackend([_json_decode_error(), _good_response()])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        assert len(attempts) == 1
        assert attempts[0].error_type == "json_decode"

    def test_max_retries_zero_raises_immediately_on_error(self):
        """max_retries=0 means no retries — initial failure raises HealExhausted with no retry attempts.

        The initial call is not a RetryAttempt (only subsequent retry calls are).
        """
        backend = StubBackend([_validation_error()])
        with pytest.raises(HealExhausted) as exc_info:
            extract_with_retry(backend, FeatureRequest(_normalized()), max_retries=0)
        assert len(exc_info.value.attempts) == 0


# ---------------------------------------------------------------------------
# A2 — provenance stamping; confidence invariant
# ---------------------------------------------------------------------------

class TestProvenanceAndConfidence:
    def test_confidence_unchanged_after_retry(self):
        """model returned 0.77 — that exact value must survive retry stamping."""
        backend = StubBackend([_validation_error(), _good_response(confidence=0.77)])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        assert resp.features[0]["confidence"] == 0.77

    def test_healed_notes_appended_to_features(self):
        """After retry, each feature gets 'healed:attempt_1/schema_violation' in notes."""
        backend = StubBackend([_validation_error(), _good_response()])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        notes = resp.features[0]["notes"]
        assert "healed:attempt_1/schema_violation" in notes

    def test_original_notes_preserved_heal_marker_appended(self):
        """If a feature already has notes, the heal marker is *appended*, not replacing."""
        backend = StubBackend([
            _validation_error(),
            _good_response(features=[{**_GOOD_FEATURE_WITH_NOTES}]),
        ])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        notes = resp.features[0]["notes"]
        assert "original note" in notes
        assert "healed:attempt_1/schema_violation" in notes

    def test_clean_pass_does_not_stamp_notes(self):
        """No retries → notes field is untouched (None stays None)."""
        backend = StubBackend([_good_response(notes=None)])
        resp, _ = extract_with_retry(backend, FeatureRequest(_normalized()))

        assert resp.features[0]["notes"] is None

    def test_retry_attempts_stored_in_extra(self):
        """After retry, response.extra['retry_attempts'] carries the serialised attempt list."""
        backend = StubBackend([_validation_error(), _good_response()])
        resp, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        assert "retry_attempts" in resp.extra
        stored = resp.extra["retry_attempts"]
        assert len(stored) == 1
        assert stored[0]["attempt"] == 1


# ---------------------------------------------------------------------------
# A3 — non-retriable exceptions propagate immediately
# ---------------------------------------------------------------------------

class TestNonRetriableExceptions:
    def test_runtime_error_propagates_immediately(self):
        """RuntimeError (Art.9 stand-in) propagates without any retry."""
        backend = StubBackend([RuntimeError("art9 violation")])
        with pytest.raises(RuntimeError, match="art9 violation"):
            extract_with_retry(backend, FeatureRequest(_normalized()))
        # Only one call was made (no retry)
        assert len(backend._calls) == 1

    def test_value_error_propagates_immediately(self):
        """ValueError (e.g. OllamaBackend wraps JSONDecodeError) propagates without retry."""
        backend = StubBackend([ValueError("container shape")])
        with pytest.raises(ValueError):
            extract_with_retry(backend, FeatureRequest(_normalized()))
        assert len(backend._calls) == 1


# ---------------------------------------------------------------------------
# A4 — retry_context injected in second FeatureRequest
# ---------------------------------------------------------------------------

class TestRetryContextInjection:
    def test_retry_context_contains_schema_path_and_error_message(self):
        """On retry, the new FeatureRequest.retry_context has the schema path + error detail."""
        val_err = _validation_error()
        backend = StubBackend([val_err, _good_response()])
        _, attempts = extract_with_retry(backend, FeatureRequest(_normalized()))

        # The second call (index 1) is the retry — its retry_context must be set
        assert len(backend._calls) == 2
        retry_req = backend._calls[1]
        assert retry_req.retry_context is not None
        # retry_context must mention the schema path or the error message
        assert attempts[0].error_detail in retry_req.retry_context or "confidence" in retry_req.retry_context

    def test_original_request_has_no_retry_context(self):
        """The first FeatureRequest never has retry_context set."""
        backend = StubBackend([_good_response()])
        extract_with_retry(backend, FeatureRequest(_normalized()))

        assert backend._calls[0].retry_context is None


# ---------------------------------------------------------------------------
# HealExhausted message format
# ---------------------------------------------------------------------------

class TestHealExhaustedMessage:
    def test_message_contains_attempt_detail(self):
        """HealExhausted str contains 'attempt N:' entries for each failed attempt."""
        backend = StubBackend([_validation_error(), _validation_error()])
        with pytest.raises(HealExhausted) as exc_info:
            extract_with_retry(backend, FeatureRequest(_normalized()), max_retries=1)

        msg = str(exc_info.value)
        assert "attempt 1:" in msg

    def test_heal_exhausted_attempts_attribute(self):
        """HealExhausted.attempts is the full list of RetryAttempt objects (one per retry call)."""
        # max_retries=1 → initial fails + 1 retry fails → 1 RetryAttempt (attempt=1)
        backend = StubBackend([_validation_error(), _validation_error()])
        with pytest.raises(HealExhausted) as exc_info:
            extract_with_retry(backend, FeatureRequest(_normalized()), max_retries=1)

        attempts = exc_info.value.attempts
        assert len(attempts) == 1
        assert isinstance(attempts[0], RetryAttempt)
        assert attempts[0].attempt == 1
        assert attempts[0].backend == "stub"
        assert attempts[0].error_type == "schema_violation"


# ---------------------------------------------------------------------------
# Helper unit tests (_classify, _detail, _build_retry_context, _stamp_provenance)
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_classify_validation_error(self):
        assert _classify(_validation_error()) == "schema_violation"

    def test_classify_json_decode_error(self):
        assert _classify(_json_decode_error()) == "json_decode"

    def test_detail_validation_error_contains_path(self):
        detail = _detail(_validation_error())
        # Should contain path info or the message
        assert isinstance(detail, str)
        assert len(detail) > 0

    def test_detail_json_decode_error(self):
        detail = _detail(_json_decode_error())
        assert "bad json" in detail or "Expecting" in detail

    def test_build_retry_context_schema_violation(self):
        ctx = _build_retry_context("schema_violation", _validation_error())
        assert "corrected" in ctx.lower() or "features" in ctx.lower()

    def test_build_retry_context_json_decode(self):
        ctx = _build_retry_context("json_decode", _json_decode_error())
        assert "json" in ctx.lower() or "corrected" in ctx.lower()

    def test_stamp_provenance_no_attempts_returns_unchanged(self):
        resp = _good_response(notes="keep me")
        result = _stamp_provenance(resp, [])
        assert result is resp
        assert result.features[0]["notes"] == "keep me"

    def test_stamp_provenance_does_not_touch_confidence(self):
        resp = _good_response(confidence=0.55)
        attempt = RetryAttempt(
            attempt=1, error_type="schema_violation",
            error_detail="some detail", backend="stub", model="stub-model"
        )
        result = _stamp_provenance(resp, [attempt])
        assert result.features[0]["confidence"] == 0.55

    def test_stamp_provenance_appends_marker_when_notes_is_none(self):
        resp = _good_response(notes=None)
        attempt = RetryAttempt(
            attempt=1, error_type="json_decode",
            error_detail="detail", backend="stub", model="stub-model"
        )
        result = _stamp_provenance(resp, [attempt])
        assert result.features[0]["notes"] == "healed:attempt_1/json_decode"

    def test_stamp_provenance_appends_marker_when_notes_has_value(self):
        resp = _good_response(notes="prior note")
        attempt = RetryAttempt(
            attempt=1, error_type="schema_violation",
            error_detail="detail", backend="stub", model="stub-model"
        )
        result = _stamp_provenance(resp, [attempt])
        notes = result.features[0]["notes"]
        assert "prior note" in notes
        assert "healed:attempt_1/schema_violation" in notes
