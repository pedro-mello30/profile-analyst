"""observability/config.py — env-driven settings for MLflow observability.

All public interface is via ``is_enabled()`` and the ``settings`` singleton.
When ``OBSERVABILITY_ENABLED`` is falsy (default), every helper in this package
is a no-op and no network connection to an MLflow server is made.
"""
from __future__ import annotations

import os


class Settings:
    """Thin env-reader; evaluated lazily so tests can monkeypatch os.environ."""

    @property
    def enabled(self) -> bool:
        return os.environ.get("OBSERVABILITY_ENABLED", "false").lower() in ("1", "true", "yes")

    @property
    def tracking_uri(self) -> str:
        return os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")

    @property
    def experiment(self) -> str:
        return os.environ.get("MLFLOW_EXPERIMENT", "influencer-rag-observability")

    @property
    def experiment_eval(self) -> str:
        return os.environ.get("MLFLOW_EXPERIMENT_EVAL", "influencer-rag-eval")


settings = Settings()


def is_enabled() -> bool:
    """Return True only when OBSERVABILITY_ENABLED=true (or 1/yes)."""
    return settings.enabled
