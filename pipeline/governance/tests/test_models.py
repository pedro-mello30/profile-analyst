"""GovernanceReport serialization roundtrip (spec-0020 §8)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pipeline.governance import (
    ContractViolation,
    GovernanceReport,
    PolicyDecision,
    RateLimitToken,
    build_report,
    compute_coverage,
)
from pipeline.governance.tests.conftest import FakeEntity, FakeEntityPool


def _make_report() -> GovernanceReport:
    report = build_report("run-abc", "account_discovery")
    report.policy_decisions.append(PolicyDecision(
        allowed=True,
        reason="robots_txt_policy=N/A",
        checked_url="https://example.com/x",
        policy_type="N/A",
        decided_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    ))
    report.violations.append(ContractViolation(
        adapter_id="bad_adapter",
        field="tier",
        expected=str({"seed", "fast", "medium", "slow"}),
        got="turbo",
        message="tier='turbo' not in valid vocabulary",
    ))
    report.total_rate_limit_waits = 2
    report.total_wait_s = 3.7
    return report


class TestGovernanceReportSerialization:
    def test_to_dict_returns_serializable(self):
        report = _make_report()
        d = report.to_dict()
        assert json.dumps(d)  # must not raise

    def test_run_id_preserved(self):
        report = _make_report()
        d = report.to_dict()
        assert d["run_id"] == "run-abc"

    def test_policy_decisions_serialized(self):
        report = _make_report()
        d = report.to_dict()
        assert len(d["policy_decisions"]) == 1
        pd = d["policy_decisions"][0]
        assert pd["allowed"] is True
        assert pd["reason"] == "robots_txt_policy=N/A"

    def test_violations_serialized(self):
        report = _make_report()
        d = report.to_dict()
        assert len(d["violations"]) == 1
        assert d["violations"][0]["field"] == "tier"

    def test_wait_stats_preserved(self):
        report = _make_report()
        d = report.to_dict()
        assert d["total_rate_limit_waits"] == 2
        assert abs(d["total_wait_s"] - 3.7) < 0.01

    def test_coverage_embedded_when_present(self):
        from types import SimpleNamespace
        adapters = [SimpleNamespace(adapter_id="a1", produces=["email"])]
        pool = FakeEntityPool([FakeEntity("email")])
        ran = {"a1": "ran"}
        coverage = compute_coverage(pool, adapters, ran, run_id="run-abc", module="test")

        report = _make_report()
        report.coverage = coverage
        d = report.to_dict()
        assert d["coverage"] is not None
        assert d["coverage"]["coverage_ratio"] == 1.0
        assert isinstance(d["coverage"]["entity_types_expected"], list)

    def test_completed_at_none_when_not_set(self):
        report = build_report("r1", "mod")
        d = report.to_dict()
        assert d["completed_at"] is None

    def test_started_at_is_iso_string(self):
        report = build_report("r1", "mod")
        d = report.to_dict()
        assert isinstance(d["started_at"], str)
        datetime.fromisoformat(d["started_at"])


class TestRateLimitToken:
    def test_context_manager_noop(self):
        token = RateLimitToken(
            adapter_id="x",
            acquired_at=datetime.now(timezone.utc),
            wait_s=0.0,
        )
        with token:
            pass  # must not raise


class TestBuildReport:
    def test_returns_governance_report(self):
        report = build_report("run1", "test_module")
        assert isinstance(report, GovernanceReport)
        assert report.run_id == "run1"
        assert report.module == "test_module"
        assert report.policy_decisions == []
        assert report.violations == []
        assert report.coverage is None
        assert report.total_rate_limit_waits == 0
        assert report.total_wait_s == 0.0
