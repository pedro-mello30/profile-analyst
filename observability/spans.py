"""observability/spans.py — Span-type constants and the @trace decorator.

Usage:
    from observability.spans import trace, CHAIN, RETRIEVER, LLM, TOOL

    @trace(TOOL)
    def my_neo4j_query(...):
        ...

When ``OBSERVABILITY_ENABLED`` is falsy the decorator is a zero-cost passthrough —
the wrapped function is returned unchanged with no import of mlflow internals.

Art. 9 redaction:
    ``redact_art9(payload)`` strips or hashes values that may carry special-
    category inferences before they are written into a span payload (spec D9, A7).
"""
from __future__ import annotations

import functools
import hashlib
import logging
from typing import Any, Callable, TypeVar

from observability.config import is_enabled

logger = logging.getLogger(__name__)

# ── Span-type taxonomy (spec D6) ─────────────────────────────────────────────
CHAIN = "CHAIN"
RETRIEVER = "RETRIEVER"
LLM = "LLM"
TOOL = "TOOL"

F = TypeVar("F", bound=Callable[..., Any])

# Field names that may carry Art. 9 special-category content.
# Values are hashed rather than logged verbatim (spec D9).
_ART9_FIELDS = frozenset({
    "caption", "bio", "caption_text", "text", "notes",
    "primary_niche", "secondary_niches", "caption_sentiment",
    "brand_affinity_signals",
})


def redact_art9(payload: Any) -> Any:
    """Recursively redact Art. 9-risk fields from a span payload.

    Strings in known Art. 9 fields are replaced with their SHA-256 prefix so
    the trace remains auditable without exposing raw special-category content.
    """
    if isinstance(payload, dict):
        return {
            k: (_hash_value(v) if k in _ART9_FIELDS and isinstance(v, str) else redact_art9(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact_art9(item) for item in payload]
    return payload


def _hash_value(v: str) -> str:
    digest = hashlib.sha256(v.encode()).hexdigest()[:12]
    return f"<redacted:art9:{digest}>"


def trace(span_type: str) -> Callable[[F], F]:
    """Decorator factory: wrap a function in an MLflow span of *span_type*.

    ``is_enabled()`` is evaluated at **call time** so tests can toggle observability
    after import. When disabled the wrapper is a zero-overhead passthrough (spec A4).
    Any MLflow error at runtime is caught and logged; the original function still runs.
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_enabled():
                return fn(*args, **kwargs)
            try:
                import mlflow  # noqa: PLC0415
                traced = mlflow.trace(fn, span_type=span_type, name=fn.__qualname__)
                return traced(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MLflow span %s (%s) failed (no-op): %s", fn.__name__, span_type, exc)
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
