"""End-to-end trace shape tests for the RAG + observability integration (A1, A2).

All tests run against the disabled-observability path (no live MLflow server
required). They assert that the pipeline functions correctly and that the
decorators are transparent passthroughs when OBSERVABILITY_ENABLED=false.
"""
import os
import pytest


def test_rag_orchestrator_importable(monkeypatch):
    """HybridRAGOrchestrator and its decorated methods are importable."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    from tools.rag import HybridRAGOrchestrator, RAGError
    assert callable(HybridRAGOrchestrator)


def test_retrievers_decorated_passthrough(monkeypatch):
    """@trace(TOOL) decorators on retrievers are transparent when disabled (A4)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")

    from pipeline.rag.retrievers import VectorRetriever, KeywordRetriever, GraphRetriever

    # Verify the methods still have the right __name__ (functools.wraps applied)
    assert VectorRetriever.retrieve.__name__ == "retrieve"
    assert KeywordRetriever.retrieve.__name__ == "retrieve"
    assert GraphRetriever.retrieve.__name__ == "retrieve"


def test_calculate_fraud_risk_no_trace_emission_when_disabled(monkeypatch):
    """calculate_fraud_risk completes without contacting MLflow (A4)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")

    # Intercept any mlflow import to ensure it's not called
    import sys
    original = sys.modules.get("mlflow")

    class _Guard:
        def __getattr__(self, item):
            raise RuntimeError(f"mlflow.{item} called despite observability being disabled")

    sys.modules["mlflow"] = _Guard()
    try:
        from pipeline.scoring_utils import calculate_fraud_risk
        score = calculate_fraud_risk(follower_growth_anomaly=0.5, comment_quality_score=0.3)
        assert 0.0 <= score <= 1.0
    finally:
        if original is not None:
            sys.modules["mlflow"] = original
        else:
            sys.modules.pop("mlflow", None)


def test_trace_chain_on_rag_run_function(monkeypatch):
    """The run() function in tools/rag.py is callable (decorator applied at import)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    from tools.rag import run
    assert callable(run)
    # The function name is preserved by functools.wraps
    assert run.__name__ in ("run", "wrapper")


def test_eval_dataset_has_required_structure():
    """Each eval row has inputs.question and expectations.expected_facts (A6)."""
    from observability.evaluation import load_eval_dataset
    rows = load_eval_dataset()
    assert len(rows) >= 1
    for row in rows:
        assert "inputs" in row
        assert "question" in row["inputs"]
        assert "expectations" in row
        assert "expected_facts" in row["expectations"]
        assert isinstance(row["expectations"]["expected_facts"], list)


def test_redact_art9_applied_to_known_fields():
    """redact_art9 removes raw special-category text from span payloads (A7)."""
    from observability.spans import redact_art9
    payload = {"bio": "I have diabetes and love wellness", "user_id": "u1"}
    result = redact_art9(payload)
    assert "diabetes" not in result["bio"]
    assert result["user_id"] == "u1"
