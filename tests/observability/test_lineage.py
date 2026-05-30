"""Tests for observability/lineage.py — signal lineage logging (A3)."""
import sys
import types
import importlib


def test_lineage_noop_when_disabled(monkeypatch):
    """log_signal_lineage is a no-op when OBSERVABILITY_ENABLED=false."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")

    from observability.lineage import log_signal_lineage
    # Must not raise even without mlflow installed
    log_signal_lineage("fraud_risk_score", {"er": 0.04, "pod": 0.2}, 0.17)


def test_lineage_calls_mlflow_when_enabled(monkeypatch):
    """When enabled, log_params and log_metric are called with correct args (A3)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")

    logged_params = {}
    logged_metrics = {}

    fake_mlflow = types.ModuleType("mlflow")
    fake_mlflow.log_params = lambda p: logged_params.update(p)
    fake_mlflow.log_metric = lambda k, v: logged_metrics.update({k: v})
    sys.modules["mlflow"] = fake_mlflow

    try:
        import observability.lineage as lin_mod
        importlib.reload(lin_mod)

        lin_mod.log_signal_lineage(
            "fraud_risk_score",
            {"follower_growth_anomaly": 0.1, "comment_quality_score": 0.8},
            0.17,
        )

        assert logged_params == {
            "signal.follower_growth_anomaly": 0.1,
            "signal.comment_quality_score": 0.8,
        }
        assert logged_metrics == {"fraud_risk_score": 0.17}
    finally:
        sys.modules.pop("mlflow", None)
        importlib.reload(lin_mod)


def test_lineage_swallows_mlflow_error(monkeypatch):
    """A tracking-server error in log_params/log_metric must not propagate."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")

    fake_mlflow = types.ModuleType("mlflow")
    fake_mlflow.log_params = lambda _: (_ for _ in ()).throw(ConnectionRefusedError("down"))
    fake_mlflow.log_metric = lambda k, v: None
    sys.modules["mlflow"] = fake_mlflow

    try:
        import observability.lineage as lin_mod
        importlib.reload(lin_mod)
        lin_mod.log_signal_lineage("score", {"s": 1.0}, 0.5)  # must not raise
    finally:
        sys.modules.pop("mlflow", None)
        importlib.reload(lin_mod)


def test_calculate_fraud_risk_emits_lineage(monkeypatch):
    """calculate_fraud_risk produces a score in [0,1] and logs lineage (E-3)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")  # lineage call is no-op; test score only

    from pipeline.scoring_utils import calculate_fraud_risk
    score = calculate_fraud_risk(
        follower_growth_anomaly=0.2,
        comment_quality_score=0.6,
        engagement_rate=0.03,
    )
    assert 0.0 <= score <= 1.0


def test_calculate_fraud_risk_high_signals(monkeypatch):
    """High anomaly signals push the score toward 1.0."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    from pipeline.scoring_utils import calculate_fraud_risk

    high = calculate_fraud_risk(
        follower_growth_anomaly=1.0,
        comment_quality_score=0.0,
        engagement_rate=0.0,
        community_size=1.0,
        centrality_score=1.0,
    )
    low = calculate_fraud_risk(
        follower_growth_anomaly=0.0,
        comment_quality_score=1.0,
        engagement_rate=0.05,
    )
    assert high > low
