"""Unit tests for pipeline.diagnostics — Layer 3 Creator Diagnostics (spec 0016 T26+T27)."""
from __future__ import annotations

import pytest

from pipeline.diagnostics import (
    compute_theme_mix,
    compute_editorial_consistency,
    compute_top_topics,
    compute_content_format_mix,
    classify_creator_archetype,
    classify_creator_size,
    classify_lifecycle_stage,
    compute_sponsorship_readiness,
    compute_brand_fit,
    compute_risk_flags,
    build_derived_insights,
    build_derived_diagnostics,
)
from pipeline.models import (
    ThemeMix,
    DossierScore,
    DerivedInsights,
    DerivedDiagnostics,
    LabeledInterpretation,
    CreatorSizeField,
)


# ── T26: Unit test classes covering acceptance criteria A4–A14 ────────────────


class TestComputeThemeMix:
    def test_maps_known_hashtags_to_themes(self):
        """Media with ['chatgpt', 'openai'] → theme_mix.values has 'ai_tools'."""
        media = [{"media_id": "m1", "hashtags": ["chatgpt", "openai"], "caption": ""}]
        result = compute_theme_mix(media)
        assert result is not None
        assert "ai_tools" in result.values

    def test_unmapped_ratio_reflects_unknown_tags(self):
        """1 mapped + 1 unmapped → unmapped_ratio = 0.5."""
        media = [{"media_id": "m1", "hashtags": ["chatgpt", "unknowntag123"], "caption": ""}]
        result = compute_theme_mix(media)
        assert result is not None
        assert result.unmapped_ratio == pytest.approx(0.5)

    def test_all_noise_returns_high_unmapped(self):
        """All noise tags → unmapped_ratio = 1.0, confidence = 0.0 (spec §5.5)."""
        media = [{"media_id": "m1", "hashtags": ["fyp", "viral", "trending"], "caption": ""}]
        result = compute_theme_mix(media)
        assert result is not None
        assert result.unmapped_ratio == pytest.approx(1.0)
        assert result.confidence == pytest.approx(0.0)

    def test_empty_returns_none(self):
        """[] → None."""
        result = compute_theme_mix([])
        assert result is None


class TestComputeEditorialConsistency:
    def test_derives_from_thematic_concentration(self):
        """theme_mix with max value 0.9, unmapped_ratio=0.0 → score=90 (A4)."""
        theme_mix = ThemeMix(
            values={"ai_tools": 0.9, "tech_general": 0.1},
            unmapped_ratio=0.0,
            confidence=1.0,
        )
        result = compute_editorial_consistency(theme_mix)
        assert result is not None
        # score = round(0.9 * 1.0 * 100) = 90
        assert result.value == 90

    def test_diverse_themes_score_low(self):
        """theme_mix with max value 0.2, unmapped_ratio=0.0 → score=20."""
        theme_mix = ThemeMix(
            values={"ai_tools": 0.2, "fitness": 0.2, "travel": 0.2, "food": 0.2, "finance": 0.2},
            unmapped_ratio=0.0,
            confidence=1.0,
        )
        result = compute_editorial_consistency(theme_mix)
        assert result is not None
        assert result.value == 20

    def test_none_theme_mix_returns_none(self):
        """None theme_mix → None."""
        assert compute_editorial_consistency(None) is None


class TestComputeTopTopics:
    def test_evidence_uses_media_ids(self):
        """evidence_media_ids contains media_id strings, NOT indices (A6)."""
        media = [
            {"media_id": "abc123", "hashtags": ["chatgpt"], "caption": "Using AI tools today"},
            {"media_id": "def456", "hashtags": ["chatgpt"], "caption": "More AI tools usage"},
        ]
        result = compute_top_topics(media)
        assert len(result) > 0
        # Find the topic backed by media IDs
        topic_entry = next((e for e in result if "chatgpt" in e.topic), None)
        assert topic_entry is not None
        # evidence_media_ids must contain string IDs, not integer indices
        for eid in topic_entry.evidence_media_ids:
            assert isinstance(eid, str)
            assert eid in ("abc123", "def456")

    def test_empty_returns_empty_list(self):
        """[] → []."""
        assert compute_top_topics([]) == []


class TestClassifyCreatorSize:
    def test_no_confidence_field(self):
        """CreatorSizeField has no 'confidence' attribute in its model_fields (A7)."""
        from pipeline.models import CreatorSizeField
        assert "confidence" not in CreatorSizeField.model_fields

    def test_micro_tier_maps_to_micro(self):
        result = classify_creator_size("Micro")
        assert result.value == "micro"

    def test_unknown_tier_maps_to_unknown(self):
        result = classify_creator_size("NonExistentTier")
        assert result.value == "unknown"


class TestClassifyLifecycleStage:
    def test_has_confidence_and_evidence(self):
        """LabeledInterpretation has confidence and evidence fields (A7)."""
        result = classify_lifecycle_stage("Mid", 0.7, 1.0)
        assert hasattr(result, "confidence")
        assert hasattr(result, "evidence")

    def test_plateau_override_when_er_below_half_benchmark(self):
        """er_vs_benchmark_ratio=0.4, tier='Mid' → value='plateaued'."""
        result = classify_lifecycle_stage("Mid", 0.7, 0.4)
        assert result.value == "plateaued"

    def test_nascent_stalled_for_micro_low_consistency(self):
        """tier='Micro', consistency=0.2 → value='nascent_stalled'."""
        result = classify_lifecycle_stage("Micro", 0.2, 1.0)
        assert result.value == "nascent_stalled"


class TestComputeSponsorshipReadiness:
    def test_ftc_at_risk_always_low(self):
        """ftc_status='at_risk', auth=100, brand=100 → value='low', matched_rule='low_v1_ftc_override' (A8)."""
        result = compute_sponsorship_readiness("at_risk", 100.0, 100.0, 1.0)
        assert result.value == "low"
        assert result.matched_rule == "low_v1_ftc_override"

    def test_high_scores_produce_high(self):
        """ftc='compliant', auth=90, brand=90, consistency=0.9 → value='high'."""
        result = compute_sponsorship_readiness("compliant", 90.0, 90.0, 0.9)
        assert result.value == "high"


class TestComputeBrandFit:
    def test_known_niche_returns_entries(self):
        """primary_niche='AI/Technology', niche_conf=1.0 → non-empty list (A9)."""
        result = compute_brand_fit("AI/Technology", 1.0, [])
        assert len(result) > 0

    def test_entries_have_required_fields(self):
        """Each entry has category, fit (high/medium/low), confidence, method (A9)."""
        result = compute_brand_fit("AI/Technology", 1.0, [])
        for entry in result:
            assert entry.category
            assert entry.fit in ("high", "medium", "low")
            assert 0.0 <= entry.confidence <= 1.0
            assert entry.method == "rule_based"

    def test_unknown_niche_returns_empty(self):
        """primary_niche='Unknown' → []."""
        result = compute_brand_fit("Unknown", 1.0, [])
        assert result == []


class TestComputeRiskFlags:
    def test_flags_have_required_fields(self):
        """Each RiskFlag has flag, severity, method, evidence (A10)."""
        flags = compute_risk_flags("Nano", "not_detected", "unknown", 80.0, 80.0, "none", 3.0)
        for f in flags:
            assert f.flag
            assert f.severity in ("high", "medium", "low")
            assert f.method
            assert isinstance(f.evidence, list)

    def test_at_risk_ftc_fires_ftc_risk_flag(self):
        """ftc_status='at_risk' → 'ftc_risk' in [f.flag for f in flags]."""
        flags = compute_risk_flags("Micro", "not_detected", "at_risk", 80.0, 80.0, "none", 3.0)
        assert "ftc_risk" in [f.flag for f in flags]

    def test_clean_profile_has_no_flags(self):
        """All-good inputs → empty list (no risk flags)."""
        # Mid tier, no pod, compliant FTC, high scores, no anomaly, good frequency
        flags = compute_risk_flags("Mid", "not_detected", "compliant", 80.0, 80.0, "none", 3.0)
        assert flags == []

    def test_multiple_flags_fire_independently(self):
        """tier='Nano' AND pod_signal='detected' → at least 2 flags."""
        flags = compute_risk_flags("Nano", "detected", "unknown", 80.0, 80.0, "none", 3.0)
        assert len(flags) >= 2


# ── T27: Orchestrator integration tests ──────────────────────────────────────


class TestOrchestrators:
    SAMPLE_MEDIA = [
        {"media_id": "m1", "media_type": "REEL", "hashtags": ["chatgpt", "aitools"], "caption": "Using AI tools daily"},
        {"media_id": "m2", "media_type": "IMAGE", "hashtags": ["openai"], "caption": "OpenAI released new models"},
    ]
    SAMPLE_FEATS = {
        "follower_tier": {"value": "Micro", "confidence": 0.9},
        "primary_niche": {"value": "AI/Technology", "confidence": 0.85},
        "secondary_niches": {"value": []},
        "er_by_followers": {"value": 4.5},
        "posting_frequency_per_week": {"value": 3.0},
        "posting_consistency_score": {"value": 0.7},
        "comment_pod_signal": {"value": "not_detected"},
        "engagement_anomaly": {"value": "none"},
        "ftc_disclosure_status": "unknown",  # top-level, not nested
        "sponsored_posts": {"value": 0},
        "likely_sponsored_undisclosed": {"value": 0},
        "total_posts": {"value": 20},
        "authenticity": {"value": 80, "signals": ["x"], "confidence": 0.8, "contributions": []},
        "brand_safety": {"value": 85, "signals": ["x"], "confidence": 0.8, "contributions": []},
    }
    SAMPLE_SCORES = {
        "authenticity": DossierScore(value=80, signals=["x"], confidence=0.8),
        "brand_safety": DossierScore(value=85, signals=["x"], confidence=0.8),
    }

    def test_build_derived_insights_returns_correct_type(self):
        result = build_derived_insights(self.SAMPLE_MEDIA, self.SAMPLE_FEATS)
        assert isinstance(result, DerivedInsights)
        assert result.computed_at  # non-empty ISO string

    def test_build_derived_diagnostics_returns_correct_type(self):
        insights = build_derived_insights(self.SAMPLE_MEDIA, self.SAMPLE_FEATS)
        result = build_derived_diagnostics(
            feats=self.SAMPLE_FEATS,
            scores=self.SAMPLE_SCORES,
            insights=insights,
            tier="Micro",
            niche="AI/Technology",
            niche_conf=0.85,
            secondary_niches=[],
            freq=3.0,
            consistency=0.7,
            ftc_status="unknown",
            pod_signal="not_detected",
            engagement_anomaly="none",
            followers=15000,
        )
        assert isinstance(result, DerivedDiagnostics)
        assert result.computed_at
        assert result.creator_archetype.value in {
            "specialist_educator", "thought_leader", "brand_builder",
            "entertainer", "lifestyle_blogger", "content_creator"
        }
        assert isinstance(result.brand_fit, list)
        assert len(result.brand_fit) > 0  # AI/Technology should produce entries
