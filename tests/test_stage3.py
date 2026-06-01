"""Stage 3 FEATURES unit tests — A3 ER exact, A4 sponsored, A5 niche, A9 Art.9.

Claude API is mocked via a fixture response — no live API call in unit tests.
"""
import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.stage3_features import (
    _build_deterministic_features,
    _compute_er_by_followers,
    _compute_sponsored_pass1,
    run,
)
from pipeline.scoring_utils import follower_tier, er_vs_benchmark

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_profile():
    raw = json.loads((FIXTURE_ROOT / "01-raw.json").read_text())
    return raw["raw_profile"], raw["raw_media"]


@pytest.fixture
def mock_llm_response():
    return [
        {"feature_id": "primary_niche", "value": "Fitness/Health", "unit": None,
         "confidence": 0.88, "method": "llm", "art9_risk": False,
         "signals": ["hashtags FitnessMotivation HealthyEating"], "notes": None},
        {"feature_id": "secondary_niches", "value": ["Lifestyle", "Food/Cooking"], "unit": None,
         "confidence": 0.75, "method": "llm", "art9_risk": False,
         "signals": ["hashtags Lifestyle MealPrep"], "notes": None},
        {"feature_id": "caption_sentiment", "value": "positive", "unit": None,
         "confidence": 0.82, "method": "llm", "art9_risk": False,
         "signals": ["motivational language"], "notes": None},
        {"feature_id": "brand_affinity_signals",
         "value": [{"brand": "NutriBoost", "category": "nutrition", "confidence": 0.95}],
         "unit": None, "confidence": 0.9, "method": "llm", "art9_risk": False,
         "signals": ["@mention NutriBoost"], "notes": None},
        {"feature_id": "likely_sponsored_undisclosed", "value": [], "unit": None,
         "confidence": 0.8, "method": "llm", "art9_risk": False,
         "signals": ["all commercial posts disclosed"], "notes": None},
        {"feature_id": "sponsorship_history",
         "value": [{"brand": "NutriBoost", "first_seen": "2026-05-24", "count": 1,
                    "disclosure_type": "paid_partnership"}],
         "unit": None, "confidence": 0.9, "method": "llm", "art9_risk": False,
         "signals": ["is_paid_partnership flag"], "notes": None},
    ]


class TestERComputation:
    def test_a3_er_exact_match(self, sample_profile):
        """A3: ER by followers computes correctly on the fixture."""
        raw_profile, media = sample_profile
        followers = raw_profile["followers"]
        er = _compute_er_by_followers(media, followers)
        # All 12 posts: compute expected
        total_eng = sum(
            (m.get("likes") or 0) + (m.get("comments") or 0)
            + (m.get("saves") or 0) + (m.get("shares") or 0)
            for m in media
        )
        expected = round((total_eng / len(media) / followers) * 100, 4)
        assert er == expected

    def test_er_none_on_zero_followers(self):
        assert _compute_er_by_followers([{"likes": 100}], 0) is None

    def test_er_none_on_empty_media(self):
        assert _compute_er_by_followers([], 10000) is None


class TestSponsoredPass1:
    def test_a4_sponsored_detected(self, sample_profile):
        """A4: ≥1 sponsored post detected on fixture with explicit #ad."""
        _, media = sample_profile
        sponsored = _compute_sponsored_pass1(media)
        assert len(sponsored) >= 1

    def test_paid_partnership_flag_detected(self):
        media = [{"media_id": "x1", "is_paid_partnership": True,
                  "hashtags": [], "caption": ""}]
        assert "x1" in _compute_sponsored_pass1(media)

    def test_ad_hashtag_detected(self):
        media = [{"media_id": "x2", "is_paid_partnership": False,
                  "hashtags": ["ad", "fitness"], "caption": ""}]
        assert "x2" in _compute_sponsored_pass1(media)

    def test_gifted_hashtag_detected(self):
        media = [{"media_id": "x3", "is_paid_partnership": False,
                  "hashtags": ["gifted"], "caption": ""}]
        assert "x3" in _compute_sponsored_pass1(media)

    def test_thanks_to_pattern_detected(self):
        media = [{"media_id": "x4", "is_paid_partnership": False,
                  "hashtags": [], "caption": "Thanks to @Brand for the gift!"}]
        assert "x4" in _compute_sponsored_pass1(media)


class TestDeterministicFeatures:
    def test_features_have_required_fields(self, sample_profile):
        raw_profile, media = sample_profile
        feats = _build_deterministic_features(raw_profile, media, 45000, 820)
        for f in feats:
            assert "feature_id" in f
            assert "confidence" in f
            assert "method" in f
            assert "art9_risk" in f
            assert "signals" in f
            assert len(f["signals"]) >= 1

    def test_follower_tier_mid(self, sample_profile):
        raw_profile, media = sample_profile
        feats = _build_deterministic_features(raw_profile, media, 45000, 820)
        tier_feat = next(f for f in feats if f["feature_id"] == "follower_tier")
        assert tier_feat["value"] == "Mid"


class TestStage3Run:
    def test_a5_niche_confidence_and_method(self, tmp_path, mock_llm_response):
        """A5: primary_niche has confidence >= 0.5, method=llm."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(mock_llm_response))]
        mock_client.messages.create.return_value = mock_msg

        out = run("sample_creator", tmp_path, anthropic_client=mock_client)
        doc = json.loads(out.read_text())

        feats = {f["feature_id"]: f for f in doc["features"]}
        niche = feats.get("primary_niche")
        assert niche is not None, "primary_niche feature missing"
        assert niche["confidence"] >= 0.5
        assert niche["method"] == "llm"

    def test_a9_art9_enforced(self, tmp_path, mock_llm_response):
        """A9: Art.9 features carry art9_risk=True after enforcement."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(mock_llm_response))]
        mock_client.messages.create.return_value = mock_msg

        out = run("sample_creator", tmp_path, anthropic_client=mock_client)
        doc = json.loads(out.read_text())

        feats = {f["feature_id"]: f for f in doc["features"]}
        # primary_niche=Fitness/Health must be flagged
        assert feats["primary_niche"]["art9_risk"] is True

    def test_forbidden_features_stripped(self, tmp_path, mock_llm_response):
        """Forbidden features injected by mock LLM are stripped."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")

        bad_response = mock_llm_response + [
            {"feature_id": "binary_gender", "value": "female", "unit": None,
             "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["test"]}
        ]
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(bad_response))]
        mock_client.messages.create.return_value = mock_msg

        out = run("sample_creator", tmp_path, anthropic_client=mock_client)
        doc = json.loads(out.read_text())
        ids = [f["feature_id"] for f in doc["features"]]
        assert "binary_gender" not in ids

    def test_extract_with_retry_is_called_by_stage3(self, tmp_path, mock_llm_response):
        """Spec 0013: Stage 3 run() calls extract_with_retry, not the backend directly."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")

        from pipeline.llm.base import FeatureResponse
        good_resp = FeatureResponse(
            features=mock_llm_response,
            model="test", backend="test", data_egress="local-only"
        )
        with patch("pipeline.stage3_features.extract_with_retry", return_value=(good_resp, [])) as mock_retry:
            mock_client = MagicMock()
            run("sample_creator", tmp_path, anthropic_client=mock_client)

        assert mock_retry.called

    def test_output_schema_valid(self, tmp_path, mock_llm_response):
        import jsonschema
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(mock_llm_response))]
        mock_client.messages.create.return_value = mock_msg

        out = run("sample_creator", tmp_path, anthropic_client=mock_client)
        doc = json.loads(out.read_text())
        schema = json.load(open("schemas/03-features.schema.json"))
        jsonschema.validate(doc, schema)
