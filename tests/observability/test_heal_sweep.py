"""tests/observability/test_heal_sweep.py — TDD for HealSweep outer loop (spec 0013 Track B)."""
from __future__ import annotations

import pytest

from tools.heal_sweep import diff_baseline, group_failures, render_report


# ── group_failures ────────────────────────────────────────────────────────────

def test_group_failures_counts_by_key():
    attempts = [
        {"error_type": "schema_violation", "error_detail": "features → 0 → confidence: 'x' is not number"},
        {"error_type": "schema_violation", "error_detail": "features → 0 → confidence: 'x' is not number"},
        {"error_type": "json_decode", "error_detail": "Expecting value: line 1"},
    ]
    groups = group_failures(attempts)
    assert groups[("schema_violation", "confidence")] == 2
    assert groups[("json_decode", "json_decode")] == 1


def test_group_failures_empty():
    assert group_failures([]) == {}


def test_group_failures_schema_violation_method():
    attempts = [
        {"error_type": "schema_violation", "error_detail": "features → 1 → method: 'bad' is not valid"},
    ]
    groups = group_failures(attempts)
    assert ("schema_violation", "method") in groups


def test_group_failures_schema_violation_value():
    attempts = [
        {"error_type": "schema_violation", "error_detail": "features → 0 → value: {} is not of type 'string'"},
    ]
    groups = group_failures(attempts)
    assert ("schema_violation", "value") in groups


def test_group_failures_skips_numeric_path_segment():
    """Numeric-only segments (array indices) should be skipped as path_key."""
    attempts = [
        {"error_type": "schema_violation", "error_detail": "features → 3: something invalid"},
    ]
    groups = group_failures(attempts)
    # Should not produce a key of "3"
    keys = [k[1] for k in groups]
    assert "3" not in keys


# ── diff_baseline ─────────────────────────────────────────────────────────────

def test_diff_baseline_flags_regression():
    baseline = {"relevance_to_query/mean": 0.82, "retrieval_groundedness/mean": 0.77}
    current  = {"relevance_to_query/mean": 0.74, "retrieval_groundedness/mean": 0.78}
    regressions = diff_baseline(current, baseline, threshold=0.05)
    assert "relevance_to_query/mean" in regressions
    assert "retrieval_groundedness/mean" not in regressions


def test_diff_baseline_no_regression():
    assert diff_baseline({"relevance_to_query/mean": 0.83}, {"relevance_to_query/mean": 0.82}) == {}


def test_diff_baseline_missing_current_metric_skipped():
    baseline = {"relevance_to_query/mean": 0.82, "other/mean": 0.5}
    current  = {"relevance_to_query/mean": 0.83}
    assert diff_baseline(current, baseline) == {}


def test_diff_baseline_exact_threshold_not_flagged():
    """A drop of exactly threshold should NOT be flagged (strict <)."""
    baseline = {"relevance_to_query/mean": 0.82}
    current  = {"relevance_to_query/mean": 0.77}  # delta = -0.05, not < -0.05
    assert diff_baseline(current, baseline, threshold=0.05) == {}


def test_diff_baseline_regression_delta():
    baseline = {"relevance_to_query/mean": 0.82}
    current  = {"relevance_to_query/mean": 0.74}
    regressions = diff_baseline(current, baseline)
    entry = regressions["relevance_to_query/mean"]
    assert entry["baseline"] == pytest.approx(0.82)
    assert entry["current"] == pytest.approx(0.74)
    assert entry["delta"] == pytest.approx(-0.08)


# ── render_report ─────────────────────────────────────────────────────────────

def test_render_report_contains_failure_table():
    groups = {("schema_violation", "confidence"): 5}
    report = render_report(groups, {}, window=30)
    assert "schema_violation" in report
    assert "confidence" in report
    assert "5" in report


def test_render_report_contains_regression_section():
    regressions = {"relevance_to_query/mean": {"baseline": 0.82, "current": 0.74, "delta": -0.08}}
    report = render_report({}, regressions, window=30)
    assert "relevance_to_query" in report
    assert "regression" in report.lower()


def test_render_report_no_issues_message():
    report = render_report({}, {}, window=30)
    assert "no failures" in report.lower() or "clean" in report.lower()


def test_render_report_sorted_by_count_descending():
    groups = {
        ("schema_violation", "method"): 2,
        ("schema_violation", "confidence"): 7,
        ("json_decode", "json_decode"): 1,
    }
    report = render_report(groups, {}, window=30)
    pos_confidence = report.index("confidence")
    pos_method = report.index("method")
    pos_json = report.index("json_decode")
    assert pos_confidence < pos_method < pos_json


def test_render_report_hypothesis_json_decode():
    groups = {("json_decode", "json_decode"): 3}
    report = render_report(groups, {}, window=30)
    assert "OLLAMA_TIMEOUT_S" in report or "truncated" in report.lower()


def test_render_report_hypothesis_high_frequency():
    groups = {("schema_violation", "confidence"): 5}
    report = render_report(groups, {}, window=30)
    # count >= 5 → high-frequency hypothesis
    assert "systematic" in report.lower() or "high-frequency" in report.lower() or "example" in report.lower()


def test_render_report_no_regression_message():
    groups = {("schema_violation", "confidence"): 2}
    report = render_report(groups, {}, window=30)
    assert "no regressions" in report.lower()
