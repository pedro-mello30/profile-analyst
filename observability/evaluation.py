"""observability/evaluation.py — RAG quality evaluation harness (spec 0006 §7).

Loads ``observability/eval/rag-eval.jsonl`` and runs ``mlflow.genai.evaluate``
with the built-in judges. Results are logged to the ``influencer-rag-eval``
experiment so quality is tracked over time.

Usage:
    OBSERVABILITY_ENABLED=true python3 -m observability.evaluation
    make eval
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from observability.config import is_enabled, settings

_EVAL_DATASET = Path(__file__).parent / "eval" / "rag-eval.jsonl"


def load_eval_dataset() -> list[dict[str, Any]]:
    """Load the versioned JSONL eval dataset."""
    rows = []
    with open(_EVAL_DATASET) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_evaluation(predict_fn: Any = None) -> dict[str, float]:
    """Run RAG quality evaluation using MLflow built-in judges.

    Args:
        predict_fn: Callable ``(question: str) -> str`` that returns an answer.
            When None a stub is used (for unit testing without a live RAG).

    Returns:
        Dict of aggregate metric names → mean scores.
    """
    if not is_enabled():
        print("Observability disabled (OBSERVABILITY_ENABLED is not set). Skipping eval.")
        return {}

    try:
        import mlflow
        import mlflow.genai  # noqa: F401
        from mlflow.genai.scorers import (  # type: ignore[import]
            RelevanceToQuery,
            RetrievalGroundedness,
            RetrievalSufficiency,
        )
    except ImportError as exc:
        print(f"mlflow[genai] not installed: {exc}\nInstall with: pip install 'mlflow[genai]>=2.14'")
        return {}

    dataset = load_eval_dataset()

    if predict_fn is None:
        def predict_fn(question: str) -> str:
            try:
                from tools.rag import run as rag_run
                manifest = rag_run(question=question)
                return manifest.get("answer", "")
            except Exception as exc:  # noqa: BLE001
                return f"[RAG error: {exc}]"

    mlflow.set_tracking_uri(settings.tracking_uri)
    mlflow.set_experiment(settings.experiment_eval)

    results = mlflow.genai.evaluate(
        data=dataset,
        predict_fn=lambda row: predict_fn(row["inputs"]["question"]),
        scorers=[
            RelevanceToQuery(),
            RetrievalGroundedness(),
            RetrievalSufficiency(),
        ],
    )

    metrics = results.metrics
    print("\n── RAG Evaluation Results ──")
    for name, value in sorted(metrics.items()):
        print(f"  {name}: {value:.3f}")
    print()

    return metrics


if __name__ == "__main__":
    metrics = run_evaluation()
    if not metrics:
        sys.exit(1)
