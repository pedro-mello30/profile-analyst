"""Unit tests for the surfaceable gate (spec 0011 T16 — truth table)."""
import pytest

from pipeline.linkage.gate import apply_gate

_BASE_CANDIDATE = {
    "platform": "twitter",
    "candidate_handle": "creator_x",
    "confidence": 0.85,
    "likelihood_ratio": 10.0,
    "feature_evidence": [
        {"feature": "handle", "agreement": 0.95, "detail": "exact"},
        {"feature": "display_name", "agreement": 0.9, "detail": "jw"},
        {"feature": "profile_photo", "agreement": 0.0, "detail": "absent"},
        {"feature": "website", "agreement": 1.0, "detail": "match"},
        {"feature": "bio", "agreement": 0.7, "detail": "jaccard"},
    ],
    "classification": "link",
    "human_review_status": "approved",
    "consent_record_id": None,
    "bio": "Photography and travel content creator",  # no Art.9 keywords
}


def test_approved_high_confidence_is_surfaceable():
    result = apply_gate([dict(_BASE_CANDIDATE)])
    assert result[0]["surfaceable"] is True
    assert result[0]["manual_review_required"] is False


def test_pending_review_is_not_surfaceable():
    c = {**_BASE_CANDIDATE, "human_review_status": "pending"}
    result = apply_gate([c])
    assert result[0]["surfaceable"] is False


def test_rejected_review_is_not_surfaceable():
    c = {**_BASE_CANDIDATE, "human_review_status": "rejected"}
    result = apply_gate([c])
    assert result[0]["surfaceable"] is False


def test_low_confidence_requires_manual_review():
    c = {**_BASE_CANDIDATE, "confidence": 0.5, "human_review_status": "approved"}
    result = apply_gate([c])
    assert result[0]["surfaceable"] is False
    assert result[0]["manual_review_required"] is True


def test_art9_adjacent_without_consent_not_surfaceable():
    c = {
        **_BASE_CANDIDATE,
        "bio": "health and wellness advocate lgbtq pride",
        "consent_record_id": None,
    }
    result = apply_gate([c])
    assert result[0]["surfaceable"] is False


def test_art9_adjacent_with_consent_can_be_surfaceable():
    c = {
        **_BASE_CANDIDATE,
        "bio": "health and wellness advocate",
        "consent_record_id": "consent-abc-123",
    }
    result = apply_gate([c])
    assert result[0]["surfaceable"] is True


def test_multi_match_flag_set_when_multiple_links_same_platform():
    c1 = {**_BASE_CANDIDATE, "candidate_handle": "creator_x"}
    c2 = {**_BASE_CANDIDATE, "candidate_handle": "creator_y"}
    result = apply_gate([c1, c2])
    assert result[0]["multi_match_flag"] is True
    assert result[1]["multi_match_flag"] is True


def test_multi_match_flag_false_for_single_link_per_platform():
    result = apply_gate([dict(_BASE_CANDIDATE)])
    assert result[0]["multi_match_flag"] is False


def test_phash_alone_cannot_surface():
    phash_only_evidence = [
        {"feature": "handle", "agreement": 0.0, "detail": "no match"},
        {"feature": "display_name", "agreement": 0.0, "detail": "no match"},
        {"feature": "profile_photo", "agreement": 0.95, "detail": "pHash match"},
        {"feature": "website", "agreement": 0.0, "detail": "no match"},
        {"feature": "bio", "agreement": 0.0, "detail": "no match"},
    ]
    c = {
        **_BASE_CANDIDATE,
        "confidence": 0.9,
        "feature_evidence": phash_only_evidence,
        "bio": "travel blog",
    }
    result = apply_gate([c])
    assert result[0]["surfaceable"] is False
