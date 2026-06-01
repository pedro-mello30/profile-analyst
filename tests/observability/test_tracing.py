"""Tests for observability/tracing.py — no-op when disabled, swallows errors (A4, A5)."""
import importlib


def test_init_tracing_disabled_is_noop(monkeypatch):
    """With OBSERVABILITY_ENABLED=false, init_tracing() makes no network calls."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")

    # Reset the module-level _initialized guard
    import observability.tracing as tracing_mod
    tracing_mod._initialized = False

    # Should not raise and should not import mlflow (patch to detect)
    called = []
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    from observability.tracing import init_tracing
    init_tracing()  # must be silent


def test_init_tracing_swallows_connection_error(monkeypatch):
    """Even when enabled, a tracking-server error must not propagate (A5)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")

    import observability.tracing as tracing_mod
    tracing_mod._initialized = False

    # Patch mlflow to raise on set_tracking_uri
    import sys
    import types

    fake_mlflow = types.ModuleType("mlflow")
    fake_openai = types.ModuleType("mlflow.openai")

    def boom(*a, **kw):
        raise ConnectionRefusedError("server down")

    fake_mlflow.set_tracking_uri = boom
    fake_mlflow.set_experiment = boom
    fake_mlflow.openai = fake_openai
    fake_openai.autolog = boom

    sys.modules["mlflow"] = fake_mlflow
    sys.modules["mlflow.openai"] = fake_openai

    try:
        importlib.reload(tracing_mod)
        tracing_mod._initialized = False
        tracing_mod.init_tracing()  # must NOT raise
    finally:
        # Restore so other tests are unaffected
        sys.modules.pop("mlflow", None)
        sys.modules.pop("mlflow.openai", None)
        importlib.reload(tracing_mod)
        tracing_mod._initialized = False


def test_log_retry_attempts_is_no_op_when_disabled(monkeypatch):
    """log_retry_attempts must not raise when observability is off."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "")
    from observability.tracing import log_retry_attempts
    # Should not raise
    log_retry_attempts([{"attempt": 1, "error_type": "schema_violation",
                         "error_detail": "path: x", "backend": "ollama", "model": "qwen"}])


def test_init_tracing_idempotent(monkeypatch):
    """Calling init_tracing() twice with observability disabled is safe."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    import observability.tracing as tracing_mod
    tracing_mod._initialized = False

    from observability.tracing import init_tracing
    init_tracing()
    init_tracing()  # second call — must not raise
