"""Tests for observability/spans.py — taxonomy constants, trace() decorator (A1, A4)."""
import os


def test_span_type_constants():
    from observability.spans import CHAIN, RETRIEVER, LLM, TOOL
    assert CHAIN == "CHAIN"
    assert RETRIEVER == "RETRIEVER"
    assert LLM == "LLM"
    assert TOOL == "TOOL"


def test_trace_passthrough_when_disabled(monkeypatch):
    """With observability off, @trace(TOOL) returns the original function result."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")

    from observability.spans import trace, TOOL

    def add(x, y):
        return x + y

    decorated = trace(TOOL)(add)
    assert decorated(2, 3) == 5


def test_trace_preserves_function_name(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    from observability.spans import trace, CHAIN

    def my_function():
        return 42

    wrapped = trace(CHAIN)(my_function)
    assert wrapped.__name__ == "my_function"
    assert wrapped() == 42


def test_trace_multiple_span_types(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    from observability.spans import trace, CHAIN, RETRIEVER, LLM, TOOL

    results = []
    for span_type in [CHAIN, RETRIEVER, LLM, TOOL]:
        @trace(span_type)
        def fn():
            return span_type

        results.append(fn())

    assert results == [CHAIN, RETRIEVER, LLM, TOOL]


def test_trace_swallows_mlflow_error_when_enabled(monkeypatch):
    """If mlflow itself raises, the original function still runs."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")

    import sys
    import types
    fake_mlflow = types.ModuleType("mlflow")
    fake_mlflow.trace = None  # not callable — will raise TypeError
    sys.modules["mlflow"] = fake_mlflow

    try:
        from observability.spans import trace, TOOL
        import importlib
        import observability.spans as spans_mod
        importlib.reload(spans_mod)

        @spans_mod.trace(spans_mod.TOOL)
        def safe_fn(x):
            return x * 3

        assert safe_fn(4) == 12  # fallback to original even when mlflow errors
    finally:
        sys.modules.pop("mlflow", None)
