"""Tests for observability/config.py — env parsing and is_enabled() gate (A4)."""
import os

import pytest


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_ENABLED", raising=False)
    # re-import to get fresh evaluation
    import importlib
    import observability.config as cfg
    importlib.reload(cfg)
    assert not cfg.is_enabled()


@pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes"])
def test_enabled_truthy_values(monkeypatch, val):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", val)
    import importlib
    import observability.config as cfg
    importlib.reload(cfg)
    assert cfg.is_enabled()


@pytest.mark.parametrize("val", ["false", "0", "no", ""])
def test_disabled_falsy_values(monkeypatch, val):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", val)
    import importlib
    import observability.config as cfg
    importlib.reload(cfg)
    assert not cfg.is_enabled()


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_EVAL", raising=False)
    from observability.config import Settings
    s = Settings()
    assert s.tracking_uri == "http://127.0.0.1:5000"
    assert s.experiment == "influencer-rag-observability"
    assert s.experiment_eval == "influencer-rag-eval"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://myserver:9000")
    monkeypatch.setenv("MLFLOW_EXPERIMENT", "my-exp")
    from observability.config import Settings
    s = Settings()
    assert s.tracking_uri == "http://myserver:9000"
    assert s.experiment == "my-exp"
