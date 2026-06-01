"""Unit tests for LinkageDocument / LinkageCandidate models (spec 0011 T5)."""
import pytest
from pydantic import ValidationError

from pipeline.models import FeatureEvidence, LinkageCandidate, LinkageDocument

_GOV = {
    "source_id": "sample-uil",
    "data_category": "public_profile",
    "tos_compliant_at_ingest": True,
    "ingested_at": "2025-01-01T00:00:00Z",
    "gdpr_basis": "legitimate_interest",
    "subject_jurisdiction": "EU",
}

_EVIDENCE = [{"feature": "handle", "agreement": 0.95, "detail": "exact match"}]

_CANDIDATE = {
    "platform": "twitter",
    "candidate_handle": "creator_x",
    "confidence": 0.82,
    "likelihood_ratio": 15.3,
    "feature_evidence": _EVIDENCE,
    "classification": "link",
    "multi_match_flag": False,
    "manual_review_required": False,
    "human_review_status": "approved",
    "consent_record_id": None,
    "surfaceable": True,
}


def test_linkage_document_round_trips():
    doc = LinkageDocument(
        handle="creator_ig",
        governance=_GOV,
        candidates=[LinkageCandidate(**_CANDIDATE)],
    )
    assert doc.handle == "creator_ig"
    assert len(doc.candidates) == 1
    assert doc.candidates[0].confidence == 0.82
    assert doc.method_version == "v3a"


def test_linkage_document_empty_candidates_allowed():
    doc = LinkageDocument(handle="creator_ig", governance=_GOV, candidates=[])
    assert doc.candidates == []


def test_candidate_rejects_empty_feature_evidence():
    bad = {**_CANDIDATE, "feature_evidence": []}
    with pytest.raises(ValidationError):
        LinkageCandidate(**bad)


def test_candidate_rejects_invalid_classification():
    bad = {**_CANDIDATE, "classification": "WRONG"}
    with pytest.raises(ValidationError):
        LinkageCandidate(**bad)


def test_candidate_rejects_invalid_review_status():
    bad = {**_CANDIDATE, "human_review_status": "unknown_status"}
    with pytest.raises(ValidationError):
        LinkageCandidate(**bad)


def test_confidence_bounds():
    for bad_conf in (-0.1, 1.1):
        bad = {**_CANDIDATE, "confidence": bad_conf}
        with pytest.raises(ValidationError):
            LinkageCandidate(**bad)


def test_feature_evidence_agreement_bounds():
    with pytest.raises(ValidationError):
        FeatureEvidence(feature="handle", agreement=1.5, detail="oob")
