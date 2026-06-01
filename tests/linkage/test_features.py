"""Unit tests for linkage features (spec 0011 T16 — feature monotonicity, pHash no-op)."""
import pytest

from pipeline.linkage.features import compute_agreement_vector


_PROFILE = {
    "handle": "creator_ig",
    "display_name": "Alex Wellness",
    "bio": "Fitness and lifestyle content creator",
    "website": "https://www.alexwellness.com",
    "profile_photo_url": None,
}

_STRONG_MATCH = {
    "platform": "twitter",
    "candidate_handle": "creator_ig",
    "display_name": "Alex Wellness",
    "bio": "Fitness and lifestyle content creator",
    "website": "https://www.alexwellness.com",
    "profile_photo_url": None,
}

_WEAK_MATCH = {
    "platform": "twitter",
    "candidate_handle": "totally_different",
    "display_name": "Someone Else",
    "bio": "Travel blogger based in Paris",
    "website": None,
    "profile_photo_url": None,
}


def test_agreement_vector_has_5_features():
    vec = compute_agreement_vector(_PROFILE, _STRONG_MATCH)
    features = {e["feature"] for e in vec.evidences}
    assert "handle" in features
    assert "display_name" in features
    assert "profile_photo" in features
    assert "website" in features
    assert "bio" in features


def test_exact_handle_match_gives_high_agreement():
    vec = compute_agreement_vector(_PROFILE, _STRONG_MATCH)
    handle_ev = next(e for e in vec.evidences if e["feature"] == "handle")
    assert handle_ev["agreement"] == 1.0


def test_strong_match_has_higher_score_than_weak():
    vec_strong = compute_agreement_vector(_PROFILE, _STRONG_MATCH)
    vec_weak = compute_agreement_vector(_PROFILE, _WEAK_MATCH)

    def total(vec):
        return sum(e["agreement"] for e in vec.evidences)

    assert total(vec_strong) > total(vec_weak)


def test_phash_noop_without_extra(monkeypatch):
    """profile_photo feature must always be present, with agreement 0.0 when no URLs."""
    vec = compute_agreement_vector(_PROFILE, _STRONG_MATCH)
    photo_ev = next(e for e in vec.evidences if e["feature"] == "profile_photo")
    assert photo_ev["agreement"] == 0.0


def test_website_exact_host_match():
    vec = compute_agreement_vector(_PROFILE, _STRONG_MATCH)
    web_ev = next(e for e in vec.evidences if e["feature"] == "website")
    assert web_ev["agreement"] == 1.0


def test_website_mismatch():
    cand = {**_STRONG_MATCH, "website": "https://www.otherdomain.com"}
    vec = compute_agreement_vector(_PROFILE, cand)
    web_ev = next(e for e in vec.evidences if e["feature"] == "website")
    assert web_ev["agreement"] == 0.0


def test_all_agreements_in_range():
    for cand in [_STRONG_MATCH, _WEAK_MATCH]:
        vec = compute_agreement_vector(_PROFILE, cand)
        for ev in vec.evidences:
            assert 0.0 <= ev["agreement"] <= 1.0
