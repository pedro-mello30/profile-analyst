"""Self-healing retry loop for LLM feature extraction (spec 0013 Track A1).

On jsonschema.ValidationError or json.JSONDecodeError the loop re-invokes the backend with
a structured error message appended as a new user turn, up to *max_retries* additional attempts.

Key invariants:
- Confidence is NEVER overridden — it stays the model's own claim.
- The initial call is NOT recorded as a RetryAttempt; only subsequent retry calls are.
  "attempt 1" = first retry, "attempt 2" = second retry, etc.
- Retries are visible only in provenance: feature notes + response.extra["retry_attempts"].
- Art.9 compliance errors (RuntimeError, ValueError, OllamaError, …) propagate immediately.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import jsonschema

from pipeline.llm.base import FeatureRequest, FeatureResponse, LLMBackend


# ── data types ─────────────────────────────────────────────────────────────────

@dataclass
class RetryAttempt:
    """Record of one retry attempt (1-based; only retry calls, not the initial call)."""
    attempt: int         # 1-based — first retry = 1, second retry = 2, …
    error_type: str      # "schema_violation" | "json_decode"
    error_detail: str    # schema path + message, or decode position
    backend: str
    model: str


class HealExhausted(Exception):
    """Raised when all retry attempts are exhausted without a valid response.

    ``attempts`` contains one entry per *retry* call (not the initial call).
    """

    def __init__(self, attempts: list[RetryAttempt]) -> None:
        self.attempts = attempts
        if attempts:
            detail = "; ".join(f"attempt {a.attempt}: {a.error_detail}" for a in attempts)
            super().__init__(f"LLM heal exhausted after {len(attempts)} attempt(s): {detail}")
        else:
            super().__init__("LLM heal exhausted after initial call (max_retries=0)")


# ── internal helpers ───────────────────────────────────────────────────────────

def _classify(exc: Exception) -> str:
    if isinstance(exc, jsonschema.ValidationError):
        return "schema_violation"
    if isinstance(exc, json.JSONDecodeError):
        return "json_decode"
    raise TypeError(f"Unclassifiable exception: {type(exc)}")


def _detail(exc: Exception) -> str:
    if isinstance(exc, jsonschema.ValidationError):
        path_parts = list(exc.absolute_path)
        if path_parts:
            path_str = " → ".join(str(p) for p in path_parts)
            return f"path → {path_str}: {exc.message}"
        return exc.message
    # json.JSONDecodeError
    return str(exc)


def _build_retry_context(error_type: str, exc: Exception) -> str:
    if error_type == "schema_violation":
        assert isinstance(exc, jsonschema.ValidationError)
        path_parts = list(exc.absolute_path)
        path_str = " → ".join(str(p) for p in path_parts) if path_parts else "(root)"
        lines = [
            "Your previous response failed schema validation.",
            f"Schema path: {path_str}",
            f"Error: {exc.message}",
            "",
            "Please return only the corrected features array as valid JSON, no explanation.",
        ]
    else:
        # json.JSONDecodeError
        lines = [
            "Your previous response could not be parsed as JSON.",
            f"Parse error: {exc}",
            "",
            "Please return only the corrected features array as valid JSON, no explanation.",
        ]
    return "\n".join(lines)


def _stamp_provenance(response: FeatureResponse, attempts: list[RetryAttempt]) -> FeatureResponse:
    """Append heal markers to feature notes and store attempt list in extra.

    Confidence is NEVER touched.
    """
    if not attempts:
        return response

    # Build the heal marker string from all attempts (in order)
    markers = [f"healed:attempt_{a.attempt}/{a.error_type}" for a in attempts]
    marker_str = "; ".join(markers)

    stamped_features = []
    for feat in response.features:
        feat = dict(feat)  # shallow copy — do not mutate callers' data
        existing = feat.get("notes")
        if existing is None:
            feat["notes"] = marker_str
        else:
            feat["notes"] = f"{existing}; {marker_str}"
        stamped_features.append(feat)

    serialised = [
        {
            "attempt": a.attempt,
            "error_type": a.error_type,
            "error_detail": a.error_detail,
            "backend": a.backend,
            "model": a.model,
        }
        for a in attempts
    ]

    return FeatureResponse(
        features=stamped_features,
        model=response.model,
        backend=response.backend,
        data_egress=response.data_egress,
        raw_text=response.raw_text,
        extra={**response.extra, "retry_attempts": serialised},
    )


# ── public API ─────────────────────────────────────────────────────────────────

_RETRIABLE = (jsonschema.ValidationError, json.JSONDecodeError)


def extract_with_retry(
    backend: LLMBackend,
    req: FeatureRequest,
    *,
    max_retries: int = 2,
) -> tuple[FeatureResponse, list[RetryAttempt]]:
    """Call *backend.extract_features*, retrying on retriable errors up to *max_retries* times.

    Only retry calls (not the initial call) generate :class:`RetryAttempt` records.
    Returns ``(response, attempts)`` where *attempts* is empty on a clean first pass.
    On exhaustion raises :class:`HealExhausted`.
    Any non-retriable exception propagates immediately.
    """
    attempts: list[RetryAttempt] = []

    # ── initial call ──────────────────────────────────────────────────────────
    try:
        response = backend.extract_features(req)
        return response, []
    except _RETRIABLE as initial_exc:
        if max_retries == 0:
            raise HealExhausted([]) from initial_exc
        last_exc: Exception = initial_exc
    # Any other exception propagates immediately (RuntimeError, ValueError, OllamaError …)

    # ── retry loop ────────────────────────────────────────────────────────────
    for retry_num in range(1, max_retries + 1):
        error_type = _classify(last_exc)
        error_detail = _detail(last_exc)
        retry_ctx = _build_retry_context(error_type, last_exc)

        retry_req = FeatureRequest(
            normalized=req.normalized,
            retry_context=retry_ctx,
        )

        try:
            response = backend.extract_features(retry_req)
            # Success — record this retry as an attempt, stamp provenance, return
            attempt = RetryAttempt(
                attempt=retry_num,
                error_type=error_type,
                error_detail=error_detail,
                backend=backend.name(),
                model=getattr(backend, "_model", None) or backend.name(),
            )
            attempts.append(attempt)
            return _stamp_provenance(response, attempts), attempts

        except _RETRIABLE as exc:
            attempt = RetryAttempt(
                attempt=retry_num,
                error_type=error_type,
                error_detail=error_detail,
                backend=backend.name(),
                model=getattr(backend, "_model", None) or backend.name(),
            )
            attempts.append(attempt)
            last_exc = exc
        # Non-retriable exceptions from retries also propagate immediately

    raise HealExhausted(attempts)
