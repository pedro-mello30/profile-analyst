"""Stage 2 NORMALIZE unit tests (A6 idempotency lives in end-to-end test)."""
import json
import shutil
import pytest
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
