"""Coverage and confidence normalization tests — AC6, AC7 (spec-0020 §7)."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from pipeline.governance import compute_coverage, normalize_confidence
from pipeline.governance.tests.conftest import FakeEntity, FakeEntityPool


class TestNormalizeConfidence:
    def test_in_range_unchanged(self):
        assert normalize_confidence(0.0) == 0.0
        assert normalize_confidence(0.5) == 0.5
        assert normalize_confidence(1.0) == 1.0

    def test_above_one_clamped(self):  # AC6
        result = normalize_confidence(1.5)
        assert result == 1.0

    def test_below_zero_clamped(self):  # AC6
        result = normalize_confidence(-0.2)
        assert result == 0.0

    def test_clamp_emits_warning(self, caplog):  # AC6
        with caplog.at_level(logging.WARNING, logger="pipeline.governance.metrics"):
            normalize_confidence(2.0)
        assert any("clamped" in r.message.lower() or "2.0" in r.message for r in caplog.records)

    def test_no_warning_when_in_range(self, caplog):
        with caplog.at_level(logging.WARNING, logger="pipeline.governance.metrics"):
            normalize_confidence(0.7)
        assert caplog.records == []

    def test_warn_if_clamped_false_suppresses_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="pipeline.governance.metrics"):
            result = normalize_confidence(5.0, warn_if_clamped=False)
        assert result == 1.0
        assert caplog.records == []

    def test_never_raises(self):
        for v in [-1e9, 0.0, 0.5, 1.0, 1e9, float("inf")]:
            result = normalize_confidence(v)
            assert 0.0 <= result <= 1.0


class TestComputeCoverage:
    def _adapter(self, adapter_id: str, produces: list) -> SimpleNamespace:
        return SimpleNamespace(adapter_id=adapter_id, produces=produces)

    def test_empty_run_coverage(self):  # AC7
        """CoverageReport always emitted, even with zero adapters."""
        report = compute_coverage(FakeEntityPool(), [], {})
        assert report is not None
        assert report.coverage_ratio == 1.0
        assert report.adapters_registered == 0

    def test_empty_adapters_vacuously_complete(self):
        report = compute_coverage(FakeEntityPool(), [], {})
        assert report.coverage_ratio == 1.0

    def test_full_coverage(self):
        adapters = [self._adapter("a1", ["email", "domain"])]
        pool = FakeEntityPool([FakeEntity("email"), FakeEntity("domain")])
        ran = {"a1": "ran"}
        report = compute_coverage(pool, adapters, ran)
        assert report.coverage_ratio == 1.0
        assert report.per_adapter_coverage["a1"] == 1.0

    def test_partial_coverage(self):
        adapters = [self._adapter("a1", ["email", "domain", "phone"])]
        pool = FakeEntityPool([FakeEntity("email")])
        ran = {"a1": "ran"}
        report = compute_coverage(pool, adapters, ran)
        assert abs(report.coverage_ratio - 1 / 3) < 0.01

    def test_zero_coverage_when_no_entities(self):
        adapters = [self._adapter("a1", ["email", "domain"])]
        pool = FakeEntityPool()
        ran = {"a1": "ran"}
        report = compute_coverage(pool, adapters, ran)
        assert report.coverage_ratio == 0.0
        assert report.per_adapter_coverage["a1"] == 0.0

    def test_skipped_adapter_absent_from_per_adapter(self):
        adapters = [self._adapter("a1", ["email"])]
        pool = FakeEntityPool()
        ran = {"a1": "skipped"}
        report = compute_coverage(pool, adapters, ran)
        assert "a1" not in report.per_adapter_coverage

    def test_counters_accurate(self):
        adapters = [
            self._adapter("a1", ["email"]),
            self._adapter("a2", ["domain"]),
            self._adapter("a3", ["phone"]),
        ]
        pool = FakeEntityPool([FakeEntity("email"), FakeEntity("domain")])
        ran = {"a1": "ran", "a2": "ran", "a3": "failed"}
        report = compute_coverage(pool, adapters, ran)
        assert report.adapters_registered == 3
        assert report.adapters_run == 2
        assert report.adapters_failed == 1
        assert report.adapters_skipped == 0

    def test_entity_types_fields_populated(self):
        adapters = [self._adapter("a1", ["email", "domain"])]
        pool = FakeEntityPool([FakeEntity("email"), FakeEntity("github_handle")])
        ran = {"a1": "ran"}
        report = compute_coverage(pool, adapters, ran)
        assert "email" in report.entity_types_expected
        assert "domain" in report.entity_types_expected
        assert "email" in report.entity_types_discovered
        assert "github_handle" in report.entity_types_discovered

    def test_multiple_adapters_produces_union(self):
        adapters = [
            self._adapter("a1", ["email"]),
            self._adapter("a2", ["domain"]),
        ]
        pool = FakeEntityPool([FakeEntity("email"), FakeEntity("domain")])
        ran = {"a1": "ran", "a2": "ran"}
        report = compute_coverage(pool, adapters, ran)
        assert report.coverage_ratio == 1.0
        assert report.entity_types_expected == {"email", "domain"}
