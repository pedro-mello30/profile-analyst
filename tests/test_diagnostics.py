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
    DerivedInsights,
    DerivedDiagnostics,
    LabeledInterpretation,
    CreatorSizeField,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

MEDIA = [
    {
        "media_id": "m001",
        "media_type": "REEL",
        "hashtags": ["chatgpt", "openai", "aitools"],
        "caption": "AI tools",
    },
    {
        "media_id": "m002",
        "media_type": "IMAGE",
        "hashtags": ["chatgpt", "productivity"],
        "caption": "productivity",
    },
]

FEATS = {
    "er_by_followers": {
        "feature_id": "er_by_followers",
        "value": 2.0,
        "confidence": 0.9,
        "method": "computed",
    },
    "follower_tier": {
        "feature_id": "follower_tier",
        "value": "Mid",
        "confidence": 1.0,
        "method": "computed",
    },
    "primary_niche": {
        "feature_id": "primary_niche",
        "value": "AI/Technology",
        "confidence": 0.85,
        "method": "llm",
    },
    "secondary_niches": {
        "feature_id": "secondary_niches",
        "value": [],
        "confidence": 0.7,
        "method": "llm",
    },
    "posting_frequency_per_week": {
        "feature_id": "posting_frequency_per_week",
        "value": 3.0,
        "confidence": 0.8,
        "method": "computed",
    },
    "posting_consistency_score": {
        "feature_id": "posting_consistency_score",
        "value": 0.7,
        "confidence": 0.8,
        "method": "computed",
    },
    "sponsored_posts": {
        "feature_id": "sponsored_posts",
        "value": [],
        "confidence": 0.9,
        "method": "computed",
    },
    "likely_sponsored_undisclosed": {
        "feature_id": "likely_sponsored_undisclosed",
        "value": [],
        "confidence": 0.7,
        "method": "inferred",
    },
    "comment_pod_signal": {
        "feature_id": "comment_pod_signal",
        "value": "unknown",
        "confidence": 0.6,
        "method": "computed",
    },
    "engagement_anomaly": {
        "feature_id": "engagement_anomaly",
        "value": "none",
        "confidence": 0.8,
        "method": "computed",
    },
}

SCORES: dict = {}  # empty for minimal fixture


# ── T26: Content analysis tests ───────────────────────────────────────────────


class TestContentAnalysis:
    def test_theme_mix_unmapped_ratio(self):
        """A5: unmapped_ratio is between 0 and 1 and mapped+unmapped sums correctly."""
        media = [
            {"media_id": "a", "hashtags": ["chatgpt", "totally_unknown_tag"], "caption": ""},
            {"media_id": "b", "hashtags": ["openai", "another_unknown"], "caption": ""},
        ]
        result = compute_theme_mix(media)
        assert result is not None
        assert 0.0 <= result.unmapped_ratio <= 1.0
        # confidence is 1 - unmapped_ratio, they should sum to 1.0
        assert abs(result.confidence + result.unmapped_ratio - 1.0) < 1e-9

    def test_editorial_consistency_from_thematic_concentration(self):
        """A4: compute_editorial_consistency takes a ThemeMix; result is int 0-100."""
        theme_mix = ThemeMix(
            values={"ai_tools": 0.8, "tech_general": 0.2},
            unmapped_ratio=0.1,
            confidence=0.9,
        )
        result = compute_editorial_consistency(theme_mix)
        assert result is not None
        assert isinstance(result.value, int)
        assert 0 <= result.value <= 100

    def test_top_topics_evidence_media_ids(self):
        """A6: evidence_media_ids contains the same media_id strings as input."""
        result = compute_top_topics(MEDIA)
        assert len(result) > 0
        # Collect all media_ids used in evidence
        all_evidence_ids = {mid for entry in result for mid in entry.evidence_media_ids}
        input_ids = {"m001", "m002"}
        # All evidence IDs must come from the input
        assert all_evidence_ids.issubset(input_ids)

    def test_content_format_mix_normalizes(self):
        """Values sum to approximately 1.0 for non-empty input."""
        result = compute_content_format_mix(MEDIA)
        assert result is not None
        total = sum(result.values.values())
        assert abs(total - 1.0) < 1e-9

    def test_theme_mix_returns_none_empty(self):
        """compute_theme_mix([]) returns None."""
        result = compute_theme_mix([])
        assert result is None


# ── T26: Classifier tests ─────────────────────────────────────────────────────


class TestClassifiers:
    def test_creator_size_no_confidence_field(self):
        """A7: classify_creator_size returns CreatorSizeField with only value and method."""
        result = classify_creator_size("Mid")
        assert isinstance(result, CreatorSizeField)
        assert result.value == "mid"
        assert result.method == "computed"
        # CreatorSizeField must NOT have a confidence attribute
        assert not hasattr(result, "confidence")

    def test_lifecycle_stage_has_confidence_and_evidence(self):
        """A7: classify_lifecycle_stage returns LabeledInterpretation with confidence > 0 and evidence."""
        result = classify_lifecycle_stage("Mid", 0.8, 1.0)
        assert isinstance(result, LabeledInterpretation)
        assert result.confidence > 0
        assert len(result.evidence) > 0

    def test_sponsorship_readiness_ftc_at_risk_always_low(self):
        """A8: ftc_status='at_risk' forces value='low' regardless of other inputs."""
        result = compute_sponsorship_readiness("at_risk", 90, 90, 0.9)
        assert result.value == "low"

    def test_brand_fit_entry_fields(self):
        """A9: each entry has category, fit, confidence, method."""
        results = compute_brand_fit("AI/Technology", 0.9, [])
        assert len(results) > 0
        for entry in results:
            assert hasattr(entry, "category")
            assert hasattr(entry, "fit")
            assert hasattr(entry, "confidence")
            assert hasattr(entry, "method")

    def test_risk_flags_entry_fields(self):
        """A10: each risk flag entry has flag, severity, method, evidence."""
        results = compute_risk_flags("Nano", "unknown", "unknown", 80, 80, "none", 2.0)
        assert len(results) > 0
        for entry in results:
            assert hasattr(entry, "flag")
            assert hasattr(entry, "severity")
            assert hasattr(entry, "method")
            assert hasattr(entry, "evidence")

    def test_risk_flags_small_audience(self):
        """small_audience flag fires when tier=Nano."""
        results = compute_risk_flags("Nano", "unknown", "unknown", 80, 80, "none", 2.0)
        flags = [r.flag for r in results]
        assert "small_audience" in flags


# ── T27: Orchestrator tests ───────────────────────────────────────────────────


class TestOrchestrators:
    def test_build_derived_insights_returns_instance(self):
        """Result is DerivedInsights with non-empty computed_at ISO string."""
        result = build_derived_insights(MEDIA, FEATS)
        assert isinstance(result, DerivedInsights)
        assert result.computed_at != ""
        # Basic ISO-8601 sanity: contains 'T' and 'Z'
        assert "T" in result.computed_at
        assert "Z" in result.computed_at

    def test_build_derived_diagnostics_returns_instance(self):
        """Result is DerivedDiagnostics with non-empty computed_at."""
        insights = build_derived_insights(MEDIA, FEATS)
        diag = build_derived_diagnostics(
            feats=FEATS,
            scores=SCORES,
            insights=insights,
            tier="Mid",
            niche="AI/Technology",
            niche_conf=0.85,
            secondary_niches=[],
            freq=3.0,
            consistency=0.7,
            ftc_status="unknown",
            pod_signal="unknown",
            engagement_anomaly="none",
            followers=50000,
        )
        assert isinstance(diag, DerivedDiagnostics)
        assert diag.computed_at != ""

    def test_creator_archetype_valid_label(self):
        """creator_archetype.value is one of the 6 valid labels."""
        valid_labels = {
            "specialist_educator",
            "thought_leader",
            "brand_builder",
            "entertainer",
            "lifestyle_blogger",
            "content_creator",
        }
        insights = build_derived_insights(MEDIA, FEATS)
        diag = build_derived_diagnostics(
            feats=FEATS,
            scores=SCORES,
            insights=insights,
            tier="Mid",
            niche="AI/Technology",
            niche_conf=0.85,
            secondary_niches=[],
            freq=3.0,
            consistency=0.7,
            ftc_status="unknown",
            pod_signal="unknown",
            engagement_anomaly="none",
            followers=50000,
        )
        assert diag.creator_archetype.value in valid_labels

    def test_brand_fit_nonempty_for_known_niche(self):
        """brand_fit is a non-empty list when niche is 'AI/Technology'."""
        insights = build_derived_insights(MEDIA, FEATS)
        diag = build_derived_diagnostics(
            feats=FEATS,
            scores=SCORES,
            insights=insights,
            tier="Mid",
            niche="AI/Technology",
            niche_conf=0.85,
            secondary_niches=[],
            freq=3.0,
            consistency=0.7,
            ftc_status="unknown",
            pod_signal="unknown",
            engagement_anomaly="none",
            followers=50000,
        )
        assert isinstance(diag.brand_fit, list)
        assert len(diag.brand_fit) > 0
