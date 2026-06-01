"""Unit tests for cohort discovery (spec 0012 T9)."""
import json
import pytest
from pathlib import Path

from pipeline.associations.cohort import CohortValidationError, discover_cohort

REAL_PROJECTS = Path(__file__).parent.parent.parent / "projects"


def _write_normalized(tmp_path: Path, handle: str, data: dict) -> None:
    profile_dir = tmp_path / handle / "00-input"
    profile_dir.mkdir(parents=True)
    (tmp_path / handle / "02-normalized.json").write_text(json.dumps(data))


_GOV = {
    "source_id": "sample",
    "data_category": "SAMPLE",
    "tos_compliant_at_ingest": True,
    "ingested_at": "2025-01-01T00:00:00Z",
    "gdpr_basis": "LEGITIMATE_INTERESTS",
    "subject_jurisdiction": "EU",
    "retention_expires_at": "2025-10-01T00:00:00Z",
}

def _make_profile(handle: str, followers: int = 1000) -> dict:
    return {
        "handle": handle,
        "platform": "instagram",
        "followers": followers,
        "following": 100,
        "post_count": 50,
        "snapshot_at": "2025-01-01T00:00:00Z",
        "governance": _GOV,
        "media": [],
    }


def test_discover_cohort_sorted_deterministic(tmp_path):
    for handle in ["creator_c", "creator_a", "creator_b"]:
        _write_normalized(tmp_path, handle, _make_profile(handle))

    cohort = discover_cohort(tmp_path)
    handles = [p.handle for p in cohort]
    assert handles == sorted(handles)
    assert len(cohort) == 3


def test_discover_cohort_single_raises(tmp_path):
    _write_normalized(tmp_path, "only_one", _make_profile("only_one"))
    with pytest.raises(CohortValidationError):
        discover_cohort(tmp_path)


def test_discover_cohort_empty_raises(tmp_path):
    with pytest.raises(CohortValidationError):
        discover_cohort(tmp_path)


def test_discover_cohort_skips_malformed(tmp_path):
    _write_normalized(tmp_path, "good_a", _make_profile("good_a"))
    _write_normalized(tmp_path, "good_b", _make_profile("good_b"))
    # write a bad file
    (tmp_path / "bad_one").mkdir()
    (tmp_path / "bad_one" / "02-normalized.json").write_text("not-json{{")

    cohort = discover_cohort(tmp_path)
    assert len(cohort) == 2
