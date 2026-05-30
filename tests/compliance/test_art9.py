"""A9 — Art.9 scanner: each category detected, defense-in-depth enforcement (spec §9.1)."""
import pytest
from pipeline.compliance import Art9Scanner, Art9Category


class TestArt9Scanner:
    def setup_method(self):
        self.scanner = Art9Scanner()

    # ── category detection ────────────────────────────────────────────────────

    def test_health_niche_detected(self):
        feat = {"feature_id": "primary_niche", "value": "fitness/health",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is not None
        assert Art9Category.HEALTH in finding.categories

    def test_sexuality_niche_detected(self):
        feat = {"feature_id": "primary_niche", "value": "lgbtq+",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is not None
        assert Art9Category.SEXUALITY in finding.categories

    def test_religion_niche_detected(self):
        feat = {"feature_id": "primary_niche", "value": "faith",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is not None
        assert Art9Category.RELIGION in finding.categories

    def test_political_niche_detected(self):
        feat = {"feature_id": "primary_niche", "value": "activism",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is not None
        assert Art9Category.POLITICAL in finding.categories

    def test_text_pattern_in_notes(self):
        feat = {"feature_id": "some_feature", "value": "travel",
                "notes": "creator discusses mental health openly",
                "confidence": 0.7, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is not None
        assert Art9Category.HEALTH in finding.categories

    def test_non_sensitive_niche_not_flagged(self):
        feat = {"feature_id": "primary_niche", "value": "Fashion",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is None

    def test_lifestyle_not_flagged(self):
        feat = {"feature_id": "primary_niche", "value": "Lifestyle",
                "confidence": 0.85, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is None

    # ── enforcement (defense-in-depth) ────────────────────────────────────────

    def test_enforce_forces_art9_risk_true(self):
        """Even if LLM said art9_risk=False, enforce() overrides it."""
        feat = {"feature_id": "primary_niche", "value": "fitness/health",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        affected = self.scanner.enforce([feat])
        assert feat["art9_risk"] is True
        assert "primary_niche" in affected

    def test_enforce_leaves_non_sensitive_unchanged(self):
        feat = {"feature_id": "primary_niche", "value": "Fashion",
                "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]}
        affected = self.scanner.enforce([feat])
        assert feat["art9_risk"] is False
        assert "primary_niche" not in affected

    def test_sweep_returns_all_findings(self):
        features = [
            {"feature_id": "primary_niche", "value": "fitness/health",
             "confidence": 0.9, "method": "llm", "art9_risk": False, "signals": ["x"]},
            {"feature_id": "secondary_niches", "value": ["Fashion"],
             "confidence": 0.7, "method": "llm", "art9_risk": False, "signals": ["x"]},
            {"feature_id": "caption_sentiment", "value": "positive",
             "confidence": 0.8, "method": "llm", "art9_risk": False, "signals": ["x"]},
        ]
        findings = self.scanner.sweep(features)
        assert len(findings) >= 2  # primary_niche (health) + caption_sentiment

    def test_secondary_niches_list_scanned(self):
        feat = {"feature_id": "secondary_niches",
                "value": ["Lifestyle", "fitness/health"],
                "confidence": 0.7, "method": "llm", "art9_risk": False, "signals": ["x"]}
        finding = self.scanner.scan_feature(feat)
        assert finding is not None
        assert Art9Category.HEALTH in finding.categories
