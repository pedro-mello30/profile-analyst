"""Stage 2 NORMALIZE unit tests (A6 idempotency lives in end-to-end test)."""
import json
import shutil
import pytest
import jsonschema
from pathlib import Path

from pipeline.stage2_normalize import run
from pipeline.compliance import ComplianceError

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


@pytest.fixture
def project_with_stage1(tmp_path):
    shutil.copy(FIXTURE_ROOT / "01-raw.json", tmp_path / "01-raw.json")
    return tmp_path


class TestStage2Normalize:
    def test_produces_schema_valid_artifact(self, project_with_stage1):
        import jsonschema
        out = run("sample_creator", project_with_stage1)
        doc = json.loads(out.read_text())
        schema = json.load(open("schemas/02-normalized.schema.json"))
        jsonschema.validate(doc, schema)

    def test_profile_fields_populated(self, project_with_stage1):
        out = run("sample_creator", project_with_stage1)
        doc = json.loads(out.read_text())
        assert doc["handle"] == "sample_creator"
        assert doc["followers"] == 45000
        assert len(doc["media"]) > 0

    def test_governance_preserved(self, project_with_stage1):
        out = run("sample_creator", project_with_stage1)
        doc = json.loads(out.read_text())
        gov = doc["governance"]
        assert gov["source_id"] == "sample"
        assert gov["tos_compliant_at_ingest"] is True

    def test_does_not_touch_stage1_artifact(self, project_with_stage1):
        mtime_before = (project_with_stage1 / "01-raw.json").stat().st_mtime
        run("sample_creator", project_with_stage1)
        mtime_after = (project_with_stage1 / "01-raw.json").stat().st_mtime
        assert mtime_before == mtime_after

    def test_expired_retention_raises(self, tmp_path):
        raw = json.loads((FIXTURE_ROOT / "01-raw.json").read_text())
        raw["_governance"]["retention_expires_at"] = "2020-01-01T00:00:00Z"
        (tmp_path / "01-raw.json").write_text(json.dumps(raw))
        with pytest.raises(ComplianceError):
            run("sample_creator", tmp_path)

    def test_merges_enrichment_signals_when_map_exists(self, project_with_stage1):
        """Stage 2 must merge enrichment_signals and enrichment_entity_count when enrichment_map.json is present."""
        enrichment_map = {
            "handle": "sample_creator",
            "signals": [{"key": "youtube_subscribers", "value": 12000}],
            "entity_pool": [{"type": "youtube_channel_id", "value": "UCxyz"}],
        }
        (project_with_stage1 / "enrichment_map.json").write_text(json.dumps(enrichment_map))
        out = run("sample_creator", project_with_stage1)
        doc = json.loads(out.read_text())
        assert "enrichment_signals" in doc, "enrichment_signals must be merged into normalized profile"
        assert doc["enrichment_signals"] == enrichment_map["signals"]
        assert doc["enrichment_entity_count"] == 1

    def test_schema_accepts_enrichment_fields(self, project_with_stage1):
        """02-normalized.schema.json must allow enrichment_signals and enrichment_entity_count."""
        enrichment_map = {
            "handle": "sample_creator",
            "signals": [{"key": "youtube_subscribers", "value": 12000}],
            "entity_pool": [{"type": "youtube_channel_id", "value": "UCxyz"}],
        }
        (project_with_stage1 / "enrichment_map.json").write_text(json.dumps(enrichment_map))
        out = run("sample_creator", project_with_stage1)
        doc = json.loads(out.read_text())
        schema = json.load(open("schemas/02-normalized.schema.json"))
        jsonschema.validate(doc, schema)


def test_all_stages_run_1b_before_2():
    """'all' pipeline must run Stage 1B before Stage 2 so enrichment feeds normalize."""
    import sys
    import importlib
    # Import the private function directly
    import importlib.util
    spec = importlib.util.spec_from_file_location("profile_analyst", "profile_analyst.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stages = mod._parse_stages("all")
    assert "1b" in stages, "Stage 1b must be in the 'all' pipeline"
    assert "2" in stages, "Stage 2 must be in the 'all' pipeline"
    assert stages.index("1b") < stages.index("2"), \
        f"Stage 1b must come before Stage 2, got order: {stages}"
