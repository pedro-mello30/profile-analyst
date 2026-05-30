"""A2 full pipeline + A6 idempotency end-to-end tests."""
import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from adapters.sample import SampleAdapter
import pipeline.stage1_ingest as s1
import pipeline.stage2_normalize as s2
import pipeline.stage3_features as s3
import pipeline.stage6_dossier as s6

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

LLM_FEATURES = [
    {"feature_id": "primary_niche", "value": "Fitness/Health", "unit": None,
     "confidence": 0.88, "method": "llm", "art9_risk": False,
     "signals": ["hashtags FitnessMotivation"], "notes": None},
    {"feature_id": "secondary_niches", "value": ["Lifestyle"], "unit": None,
     "confidence": 0.75, "method": "llm", "art9_risk": False,
     "signals": ["hashtags Lifestyle"], "notes": None},
    {"feature_id": "caption_sentiment", "value": "positive", "unit": None,
     "confidence": 0.82, "method": "llm", "art9_risk": False,
     "signals": ["motivational language"], "notes": None},
    {"feature_id": "brand_affinity_signals", "value": [], "unit": None,
     "confidence": 0.8, "method": "llm", "art9_risk": False,
     "signals": ["no brand mentions"], "notes": None},
    {"feature_id": "likely_sponsored_undisclosed", "value": [], "unit": None,
     "confidence": 0.8, "method": "llm", "art9_risk": False,
     "signals": ["all commercial posts disclosed"], "notes": None},
    {"feature_id": "sponsorship_history", "value": [], "unit": None,
     "confidence": 0.8, "method": "llm", "art9_risk": False,
     "signals": ["detected from hashtags"], "notes": None},
]


@pytest.fixture
def mock_client():
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(LLM_FEATURES))]
    client.messages.create.return_value = msg
    return client


@pytest.fixture
def pipeline_run(tmp_path, mock_client):
    """Run the full pipeline 1→2→3→6 in a temp directory."""
    adapter = SampleAdapter(projects_root=Path("projects"))
    s1.run("sample_creator", adapter, tmp_path)
    s2.run("sample_creator", tmp_path)
    s3.run("sample_creator", tmp_path, anthropic_client=mock_client)
    s6.run("sample_creator", tmp_path)
    return tmp_path


class TestFullPipeline:
    def test_a2_all_artifacts_exist(self, pipeline_run):
        """A2: full pipeline produces all stage artifacts."""
        for name in ["01-raw.json", "02-normalized.json", "03-features.json",
                     "06-dossier.json", "report.md"]:
            assert (pipeline_run / name).exists(), f"Missing {name}"

    def test_a2_all_artifacts_schema_valid(self, pipeline_run):
        """A2: all artifacts are schema-valid."""
        import jsonschema
        for stage, schema_file in [
            ("01-raw.json", "01-raw.schema.json"),
            ("02-normalized.json", "02-normalized.schema.json"),
            ("03-features.json", "03-features.schema.json"),
            ("06-dossier.json", "06-dossier.schema.json"),
        ]:
            doc = json.loads((pipeline_run / stage).read_text())
            schema = json.load(open(f"schemas/{schema_file}"))
            jsonschema.validate(doc, schema)

    def test_a6_stage2_rerun_does_not_touch_stage1(self, pipeline_run):
        """A6: re-running stage 2 overwrites only 02-normalized.json."""
        mtime_raw = (pipeline_run / "01-raw.json").stat().st_mtime
        s2.run("sample_creator", pipeline_run)
        assert (pipeline_run / "01-raw.json").stat().st_mtime == mtime_raw

    def test_a8_dossier_scores_explainable(self, pipeline_run):
        """A8: every score has non-empty signals; compliance_flags present."""
        doc = json.loads((pipeline_run / "06-dossier.json").read_text())
        for name, score in doc["scores"].items():
            assert len(score["signals"]) >= 1
        assert "compliance_flags" in doc

    def test_dossier_provenance_complete(self, pipeline_run):
        doc = json.loads((pipeline_run / "06-dossier.json").read_text())
        prov = doc["provenance"]
        assert prov["source_id"] == "sample"
        assert "ingest" in prov["stages_run"]
        assert "dossier" in prov["stages_run"]
