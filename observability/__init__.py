"""observability — MLflow tracing, signal lineage, and evaluation for the pipeline.

Public API (all helpers are no-ops when OBSERVABILITY_ENABLED is falsy):

    from observability import init_tracing, trace, CHAIN, RETRIEVER, LLM, TOOL
    from observability import log_signal_lineage
    from observability.config import is_enabled, settings

Spec: specs/0006-mlflow-observability/spec.md
"""
from observability.config import is_enabled, settings  # noqa: F401
from observability.tracing import init_tracing  # noqa: F401
from observability.spans import trace, CHAIN, RETRIEVER, LLM, TOOL  # noqa: F401
from observability.lineage import log_signal_lineage  # noqa: F401

__all__ = [
    "init_tracing",
    "trace",
    "CHAIN",
    "RETRIEVER",
    "LLM",
    "TOOL",
    "log_signal_lineage",
    "is_enabled",
    "settings",
]
