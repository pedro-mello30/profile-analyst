"""Stage 1 INGEST unit tests."""
import json
import os
import pytest
from pathlib import Path

from adapters.sample import SampleAdapter
from pipeline.stage1_ingest import run
from pipeline.compliance import TosComplianceError
from adapters.base import SourceAdapter

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


class _BadAdapter(SourceAdapter):
    source_id = "bad"
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


class TestStage1Ingest:
    def test_produces_schema_valid_artifact(self, tmp_path):
        import jsonschema
        adapter = SampleAdapter(projects_root=Path("projects"))
        out = run("sample_creator", adapter, tmp_path)
        assert out.exists()
        doc = json.loads(out.read_text())
        schema = json.load(open("schemas/01-raw.schema.json"))
        jsonschema.validate(doc, schema)

    def test_all_governance_fields_present(self, tmp_path):
        from pipeline.compliance import REQUIRED_GOVERNANCE_FIELDS
        adapter = SampleAdapter(projects_root=Path("projects"))
        out = run("sample_creator", adapter, tmp_path)
        doc = json.loads(out.read_text())
        assert set(doc["_governance"].keys()) == REQUIRED_GOVERNANCE_FIELDS

    def test_tos_gate_rejects_noncompliant(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ALLOW_NONCOMPLIANT", raising=False)
        with pytest.raises(TosComplianceError):
            run("sample_creator", _BadAdapter(), tmp_path)

    def test_atomic_write_no_tmp_left(self, tmp_path):
        adapter = SampleAdapter(projects_root=Path("projects"))
        run("sample_creator", adapter, tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_idempotent_on_rerun(self, tmp_path):
        adapter = SampleAdapter(projects_root=Path("projects"))
        out1 = run("sample_creator", adapter, tmp_path)
        doc1 = json.loads(out1.read_text())
        out2 = run("sample_creator", adapter, tmp_path)
        doc2 = json.loads(out2.read_text())
        # Core fields (except ingested_at / retention_expires_at) match
        assert doc1["handle"] == doc2["handle"]
        assert doc1["raw_media"] == doc2["raw_media"]
