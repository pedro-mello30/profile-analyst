"""Unit tests for Fellegi-Sunter scoring (spec 0011 T16 — LR→threshold mapping)."""
import pytest

from pipeline.linkage.scoring import score_candidate, T_LINK, T_POSSIBLE, SURFACE_THRESHOLD


_PERFECT_EVIDENCE = [
    {"feature": "handle", "agreement": 1.0, "detail": "exact"},
    {"feature": "display_name", "agreement": 0.95, "detail": "jw"},
    {"feature": "profile_photo", "agreement": 0.0, "detail": "absent"},
    {"feature": "website", "agreement": 1.0, "detail": "host match"},
    {"feature": "bio", "agreement": 0.8, "detail": "jaccard"},
]

_ZERO_EVIDENCE = [
    {"feature": "handle", "agreement": 0.0, "detail": "no match"},
    {"feature": "display_name", "agreement": 0.0, "detail": "no match"},
    {"feature": "profile_photo", "agreement": 0.0, "detail": "absent"},
    {"feature": "website", "agreement": 0.0, "detail": "no match"},
    {"feature": "bio", "agreement": 0.0, "detail": "no match"},
]


def test_high_agreement_produces_link():
    conf, lr, cls = score_candidate(_PERFECT_EVIDENCE)
    assert cls == "link"
    assert lr >= T_LINK


def test_zero_agreement_produces_non_link():
    conf, lr, cls = score_candidate(_ZERO_EVIDENCE)
    assert cls == "non_link"
    assert lr < T_POSSIBLE


def test_confidence_in_0_1():
    for evidence in [_PERFECT_EVIDENCE, _ZERO_EVIDENCE]:
        conf, _, _ = score_candidate(evidence)
        assert 0.0 <= conf <= 1.0


def test_high_confidence_near_1_for_perfect_match():
    conf, _, _ = score_candidate(_PERFECT_EVIDENCE)
    assert conf >= SURFACE_THRESHOLD


def test_low_confidence_for_zero_match():
    conf, _, _ = score_candidate(_ZERO_EVIDENCE)
    assert conf < SURFACE_THRESHOLD


def test_monotonicity_partial_vs_none():
    partial = [
        {"feature": "handle", "agreement": 0.8, "detail": "jw"},
        {"feature": "display_name", "agreement": 0.0, "detail": "no"},
        {"feature": "profile_photo", "agreement": 0.0, "detail": "absent"},
        {"feature": "website", "agreement": 0.0, "detail": "no"},
        {"feature": "bio", "agreement": 0.0, "detail": "no"},
    ]
    conf_partial, _, _ = score_candidate(partial)
    conf_none, _, _ = score_candidate(_ZERO_EVIDENCE)
    assert conf_partial > conf_none
