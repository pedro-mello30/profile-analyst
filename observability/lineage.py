"""observability/lineage.py — GDPR Art. 22 signal-lineage logging.

Every score that can affect a creator (fraud risk, brand fit, etc.) MUST call
``log_signal_lineage`` so the trace answers: which signals, what weights, what
final score, which model/params produced the answer.

Explainability chain:
  - 0001  ``06-dossier.json`` ``scores[].signals[]``  (human-readable per-run)
  - 0002  ``CONTRIBUTED_TO {weight}`` / ``HAS_SIGNAL`` edges  (queryable in Neo4j)
  - 0003  query manifest ``asked_at`` / ``model``              (per-NL-query)
  - 0006  MLflow params ``signal.*`` + metric ``<score_name>`` (durable, searchable)

This module is the 0006 layer. It is a no-op when observability is disabled.
"""
from __future__ import annotations

import logging

from observability.config import is_enabled

logger = logging.getLogger(__name__)


def log_signal_lineage(
    score_name: str,
    signals: dict[str, float],
    score: float,
) -> None:
    """Log signal provenance for a decision score to the active MLflow run.

    Args:
        score_name: Metric key written to MLflow (e.g. ``"fraud_risk_score"``).
        signals: Mapping of signal name → value that contributed to the score.
            Each entry is logged as a param ``signal.<name>``.
        score: The final computed score value (logged as a metric).

    The function is best-effort: any MLflow error is logged at WARNING and
    swallowed so a tracking-server outage never breaks the pipeline (spec D8).
    """
    if not is_enabled():
        return

    try:
        import mlflow  # noqa: PLC0415

        mlflow.log_params({f"signal.{k}": v for k, v in signals.items()})
        mlflow.log_metric(score_name, score)
    except Exception as exc:  # noqa: BLE001
        logger.warning("log_signal_lineage failed (lineage not recorded): %s", exc)
