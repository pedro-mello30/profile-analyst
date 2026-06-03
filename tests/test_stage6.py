"""Stage 6 DOSSIER unit tests — A8 scores explainable, scoring math, schema validity."""
import json
import shutil
import pytest
from pathlib import Path

from pydantic import ValidationError

from pipeline.models import DossierScore
from pipeline.stage6_dossier import (
    index_features,
    score_engagement_quality,
    score_authenticity,
    score_sponsorship_transparency,
    score_brand_safety,
    build_scores,
    run,
)
from pipeline.scoring_utils import TIER_BENCHMARK_ER, EQS_WEIGHTS, clamp, er_vs_benchmark

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_feats():
    doc = json.loads((FIXTURE_ROOT / "03-features.json").read_text())
    return index_features(doc)


@pytest.fixture
def project_with_stages(tmp_path):
    shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
    shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
    return tmp_path


class TestDossierScoreModel:
    def test_signals_min_length_1(self):
        with pytest.raises(ValidationError):
            DossierScore(value=50, signals=[], confidence=0.8)

    def test_valid_score_accepted(self):
        s = DossierScore(value=75, signals=["er_by_followers=3.5"], confidence=0.9)
        assert s.value == 75

    def test_value_clamped_range(self):
        with pytest.raises(ValidationError):
            DossierScore(value=101, signals=["x"], confidence=0.8)
        with pytest.raises(ValidationError):
            DossierScore(value=-1, signals=["x"], confidence=0.8)


class TestScoringMath:
    def test_er_at_benchmark_gives_50(self):
        """EQS: ER exactly at tier benchmark → er_component == 50."""
        tier = "Mid"
        er = TIER_BENCHMARK_ER[tier]  # 0.73%
        component = er_vs_benchmark(er, tier)
        assert component == pytest.approx(50.0)

    def test_er_at_double_benchmark_gives_100(self):
        tier = "Mid"
        er = TIER_BENCHMARK_ER[tier] * 2
        component = er_vs_benchmark(er, tier)
        assert component == pytest.approx(100.0)

    def test_pod_penalty_minus_20(self):
        """Comment pod signal detected → EQS decreases by exactly 20."""
        feats_no_pod = {
            "er_by_followers": {"feature_id": "er_by_followers", "value": 0.73,
                                  "confidence": 1.0, "method": "computed"},
            "follower_tier": {"feature_id": "follower_tier", "value": "Mid",
                               "confidence": 1.0, "method": "computed"},
            "comments_per_post_avg": {"feature_id": "comments_per_post_avg", "value": 30.0,
                                       "confidence": 1.0, "method": "computed"},
            "posting_consistency_score": {"feature_id": "posting_consistency_score",
                                           "value": 1.0, "confidence": 1.0, "method": "computed"},
            "follower_following_ratio": {"feature_id": "follower_following_ratio", "value": 10.0,
                                          "confidence": 1.0, "method": "computed"},
        }
        feats_pod = dict(feats_no_pod)
        feats_pod["comment_pod_signal"] = {"feature_id": "comment_pod_signal",
                                            "value": "detected", "confidence": 0.8,
                                            "method": "llm"}

        score_without = score_engagement_quality(feats_no_pod).value
        score_with = score_engagement_quality(feats_pod).value
        assert score_without - score_with == pytest.approx(20, abs=1)

    def test_authenticity_neutral_baseline(self):
        """Authenticity with no data → 50 (all components neutral at 50; weights sum to 1.0)."""
        score = score_authenticity({})
        assert score.value == 50


class TestStage6Run:
    def test_a2_schema_valid(self, project_with_stages):
        import jsonschema
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        schema = json.load(open("schemas/06-dossier.schema.json"))
        jsonschema.validate(doc, schema)

    def test_a8_all_scores_have_signals(self, project_with_stages):
        """A8: every dossier score has non-empty signals; compliance_flags present."""
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        for name, score in doc["scores"].items():
            assert len(score["signals"]) >= 1, f"{name} has empty signals"
        assert "compliance_flags" in doc

    def test_report_md_generated(self, project_with_stages):
        run("sample_creator", project_with_stages)
        report = (project_with_stages / "report.md").read_text()
        assert "sample_creator" in report
        assert "Engagement Quality" in report

    def test_idempotent_scores(self, project_with_stages):
        """Re-running stage 6 produces identical scores (modulo generated_at / dossier_id)."""
        out1 = run("sample_creator", project_with_stages)
        doc1 = json.loads(out1.read_text())
        out2 = run("sample_creator", project_with_stages)
        doc2 = json.loads(out2.read_text())
        assert doc1["scores"] == doc2["scores"]
        assert doc1["compliance_flags"] == doc2["compliance_flags"]

    def test_art9_features_in_compliance_flags(self, project_with_stages):
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        # primary_niche=Fitness/Health should be flagged
        assert len(doc["compliance_flags"]["art9_features"]) >= 1


class TestDerivedDiagnosticsInDossier:
    def test_derived_blocks_present(self, project_with_stages):
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        assert "derived_insights" in doc
        assert "derived_diagnostics" in doc

    def test_derived_diagnostics_has_all_sub_keys(self, project_with_stages):
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        dd = doc["derived_diagnostics"]
        for key in ("creator_archetype", "creator_size", "lifecycle_stage",
                    "sponsorship_readiness", "brand_fit", "risk_flags"):
            assert key in dd, f"Missing key: {key}"

    def test_creator_archetype_value_nonempty(self, project_with_stages):
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        assert doc["derived_diagnostics"]["creator_archetype"]["value"]

    def test_brand_fit_is_list(self, project_with_stages):
        out = run("sample_creator", project_with_stages)
        doc = json.loads(out.read_text())
        assert isinstance(doc["derived_diagnostics"]["brand_fit"], list)


class TestDiagnosticsInReport:
    def test_all_diagnostic_sections_present(self, project_with_stages):
        run("sample_creator", project_with_stages)
        report = (project_with_stages / "report.md").read_text()
        for marker in ("Creator Archetype", "Lifecycle Stage", "Brand Fit",
                       "Risk", "Sponsorship Readiness"):
            assert marker in report, f"Missing section: {marker}"
