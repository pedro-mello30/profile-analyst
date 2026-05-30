"""Fairness & bias guards — forbidden feature stripping, demographic humility (spec §9.5)."""
import pytest
from pipeline.compliance import (
    strip_forbidden_features,
    assert_demographic_inference_humility,
    ComplianceError,
)


def _feat(fid, value=None, confidence=0.7, method="computed"):
    return {
        "feature_id": fid,
        "value": value or fid,
        "confidence": confidence,
        "method": method,
        "art9_risk": False,
        "signals": ["test"],
    }


class TestStripForbiddenFeatures:
    def test_binary_gender_dropped(self):
        features = [_feat("binary_gender"), _feat("er_by_followers", 3.5)]
        kept, dropped = strip_forbidden_features(features)
        assert "binary_gender" in dropped
        assert len(kept) == 1
        assert kept[0]["feature_id"] == "er_by_followers"

    def test_ethnicity_dropped(self):
        features = [_feat("ethnicity"), _feat("follower_tier", "Mid")]
        kept, dropped = strip_forbidden_features(features)
        assert "ethnicity" in dropped
        assert len(kept) == 1

    def test_race_dropped(self):
        features = [_feat("race")]
        kept, dropped = strip_forbidden_features(features)
        assert "race" in dropped
        assert kept == []

    def test_audience_gender_skew_allowed(self):
        features = [_feat("audience_gender_skew", 0.55, confidence=0.6, method="inferred")]
        kept, dropped = strip_forbidden_features(features)
        assert dropped == []
        assert len(kept) == 1

    def test_clean_features_unchanged(self):
        features = [_feat("er_by_followers", 3.5), _feat("primary_niche", "Lifestyle")]
        kept, dropped = strip_forbidden_features(features)
        assert dropped == []
        assert len(kept) == 2


class TestDemographicHumility:
    def test_demographic_confidence_1_raises(self):
        features = [_feat("audience_gender_skew", 0.55, confidence=1.0, method="inferred")]
        with pytest.raises(ComplianceError) as exc_info:
            assert_demographic_inference_humility(features)
        assert "confidence=1.0" in str(exc_info.value)

    def test_demographic_method_computed_raises(self):
        features = [_feat("audience_gender_skew", 0.55, confidence=0.6, method="computed")]
        with pytest.raises(ComplianceError) as exc_info:
            assert_demographic_inference_humility(features)
        assert "method=" in str(exc_info.value)

    def test_demographic_inferred_low_confidence_passes(self):
        features = [_feat("audience_gender_skew", 0.55, confidence=0.6, method="inferred")]
        assert_demographic_inference_humility(features)  # should not raise

    def test_non_demographic_features_ignored(self):
        features = [_feat("er_by_followers", 3.5, confidence=1.0, method="computed")]
        assert_demographic_inference_humility(features)  # should not raise
