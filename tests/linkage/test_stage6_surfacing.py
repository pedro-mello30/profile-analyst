"""Integration tests for Stage 6 linkage surfacing (spec 0011 T22)."""
import json
import os
from pathlib import Path

import pytest

from pipeline.stage6_dossier import _load_linkage_block

_SURFACEABLE_CANDIDATE = {
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
    "surfaceable": True,
    "multi_match_flag": False,
    "manual_review_required": False,
    "bio": "Photography and travel content",
}

_NON_SURFACEABLE = {**_SURFACEABLE_CANDIDATE, "surfaceable": False, "human_review_status": "pending"}


def _write_linkage(project_dir: Path, candidates: list) -> None:
    doc = {
        "handle": "test_creator",
        "method_version": "v3a",
        "governance": {
            "source_id": "sample_uil",
            "data_category": "public_profile",
            "tos_compliant_at_ingest": True,
            "ingested_at": "2025-01-01T00:00:00Z",
            "gdpr_basis": "LEGITIMATE_INTERESTS",
            "subject_jurisdiction": "EU",
        },
        "candidates": candidates,
    }
    (project_dir / "04-linkage.json").write_text(json.dumps(doc))


def test_surfaceable_candidate_populates_linkage_block(tmp_path):
    _write_linkage(tmp_path, [_SURFACEABLE_CANDIDATE])
    block = _load_linkage_block(tmp_path)
    assert block["status"] == "complete"
    assert len(block["candidates"]) == 1


def test_no_surfaceable_candidate_keeps_deferred(tmp_path):
    _write_linkage(tmp_path, [_NON_SURFACEABLE])
    block = _load_linkage_block(tmp_path)
    assert block["status"] == "deferred"
    assert block["candidates"] == []


def test_absent_linkage_artifact_keeps_deferred(tmp_path):
    block = _load_linkage_block(tmp_path)
    assert block["status"] == "deferred"
    assert block["candidates"] == []


def test_gate_reapplied_pending_review_not_surfaced(tmp_path):
    cand = {**_SURFACEABLE_CANDIDATE, "surfaceable": True, "human_review_status": "pending"}
    _write_linkage(tmp_path, [cand])
    block = _load_linkage_block(tmp_path)
    # Gate re-runs: pending review → not surfaceable despite surfaceable=True in file
    assert block["status"] == "deferred"
