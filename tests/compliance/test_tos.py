"""A7 — ToS gate, governance completeness (spec §9.4, §3)."""
import os
import pytest

from adapters.sample import SampleAdapter
from pipeline.compliance import (
    enforce_tos_gate,
    build_governance_block,
    assert_governance_complete,
    TosComplianceError,
    ComplianceError,
    REQUIRED_GOVERNANCE_FIELDS,
)
from adapters.base import SourceAdapter
from datetime import datetime, timezone


class _NonCompliantAdapter(SourceAdapter):
    source_id = "bad_source"
    data_category = "PUBLIC_SCRAPE"
    tos_compliant = False
    auth_type = "NONE"
    requires_creator_consent = False
    calls_per_window = 0
    window_seconds = 3600
    available_fields: set = set()
    estimated_fields: set = set()
    gdpr_basis = "NONE"
    requires_lia = False
    max_retention_days = 30
    deletion_on_request = True

    def fetch_profile(self, handle): return {}
    def fetch_media(self, handle, limit=20): return []


class TestTosGate:
    def test_compliant_adapter_passes(self):
        adapter = SampleAdapter()
        enforce_tos_gate(adapter)  # should not raise

    def test_noncompliant_raises(self, monkeypatch):
        monkeypatch.delenv("ALLOW_NONCOMPLIANT", raising=False)
        adapter = _NonCompliantAdapter()
        with pytest.raises(TosComplianceError) as exc_info:
            enforce_tos_gate(adapter)
        assert "bad_source" in str(exc_info.value)
        assert "PUBLIC_SCRAPE" in str(exc_info.value)

    def test_noncompliant_allowed_by_env(self, monkeypatch):
        monkeypatch.setenv("ALLOW_NONCOMPLIANT", "true")
        adapter = _NonCompliantAdapter()
        enforce_tos_gate(adapter)  # should not raise

    def test_allow_noncompliant_exact_match_only(self, monkeypatch):
        """Only exact string 'true' bypasses the gate."""
        for bad in ("True", "TRUE", "1", "yes", ""):
            monkeypatch.setenv("ALLOW_NONCOMPLIANT", bad)
            adapter = _NonCompliantAdapter()
            with pytest.raises(TosComplianceError):
                enforce_tos_gate(adapter)


class TestGovernanceBlock:
    def test_all_eight_fields_present(self):
        adapter = SampleAdapter()
        now = datetime.now(timezone.utc)
        gov = build_governance_block(adapter, subject_jurisdiction="BR", ingested_at=now)
        assert set(gov.keys()) == REQUIRED_GOVERNANCE_FIELDS

    def test_retention_computed_correctly(self):
        adapter = SampleAdapter()
        now = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
        gov = build_governance_block(adapter, subject_jurisdiction="BR", ingested_at=now)
        assert gov["retention_expires_at"] == "2026-08-28T10:00:00Z"

    def test_assert_governance_complete_passes(self):
        adapter = SampleAdapter()
        now = datetime.now(timezone.utc)
        gov = build_governance_block(adapter, subject_jurisdiction="BR", ingested_at=now)
        assert_governance_complete(gov)  # should not raise

    def test_assert_governance_complete_raises_on_missing(self):
        partial = {"source_id": "sample", "data_category": "SAMPLE"}
        with pytest.raises(ComplianceError) as exc_info:
            assert_governance_complete(partial)
        assert "missing fields" in str(exc_info.value).lower()
