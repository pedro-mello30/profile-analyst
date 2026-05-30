"""observability/tracing.py — MLflow tracking init + Ollama autolog.

Call ``init_tracing()`` once at process start (CLI entrypoint, RAG entrypoint).
It is idempotent and best-effort: a server outage or any setup error is logged
at WARNING and swallowed — it never propagates to the caller (spec D8, A5).
"""
from __future__ import annotations

import logging
import threading

from observability.config import is_enabled, settings

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False


def init_tracing() -> None:
    """Configure MLflow and enable Ollama autolog.

    - No-op when ``OBSERVABILITY_ENABLED`` is falsy (spec D8, A4).
    - Swallows any connection / setup error (spec A5).
    - Idempotent: safe to call from multiple code paths (spec B-2).
    """
    global _initialized

    if not is_enabled():
        return

    with _init_lock:
        if _initialized:
            return
        try:
            import mlflow
            import mlflow.openai  # type: ignore[import]

            mlflow.set_tracking_uri(settings.tracking_uri)
            mlflow.set_experiment(settings.experiment)
            mlflow.openai.autolog()  # D2: auto-trace Ollama via OpenAI-compat SDK
            _initialized = True
            logger.info(
                "MLflow observability enabled: uri=%s experiment=%s",
                settings.tracking_uri,
                settings.experiment,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MLflow init failed (observability degraded to no-op): %s", exc)
