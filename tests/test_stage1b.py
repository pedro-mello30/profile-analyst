import json
import pytest
from pathlib import Path
from unittest.mock import patch
from pipeline.stage1b_enrichment import run, list_adapters

FIXTURE_RAW = {
    "handle": "filipelauar",
    "platform": "instagram",
    "_governance": {
        "source_id": "apify_instagram",
        "data_category": "PUBLIC_SCRAPE",
        "tos_compliant_at_ingest": True,
        "ingested_at": "2026-06-02T21:00:00Z",
        "gdpr_basis": "LEGITIMATE_INTERESTS",
        "subject_jurisdiction": "UNKNOWN",
        "retention_expires_at": "2027-06-02T21:00:00Z",
        "consent_record_id": None,
    },
    "raw_profile": {
        "handle": "filipelauar",
        "display_name": "Filipe Lauar",
        "website": "https://linktr.ee/vidacomia",
        "bio": "Podcast @podcast.lifewithai",
    },
    "raw_media": [],
}


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "01-raw.json").write_text(json.dumps(FIXTURE_RAW))
    return tmp_path


def test_run_creates_enrichment_map(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        out = run("filipelauar", project_dir, fast_only=True)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["handle"] == "filipelauar"
    assert "entity_pool" in data
    assert "adapter_runs" in data
    assert "compliance" in data


def test_run_creates_status_file(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir, fast_only=True)
    status = json.loads((project_dir / "enrichment_status.json").read_text())
    assert status["dossier_version"] == "v1"
    assert status["v1_ready_at"] is not None


def test_run_idempotent(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
        run("filipelauar", project_dir)
    data = json.loads((project_dir / "enrichment_map.json").read_text())
    assert data["handle"] == "filipelauar"


def test_run_without_raw_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Stage 1 artifact not found"):
        run("filipelauar", tmp_path)


def test_run_reads_raw_not_normalized(tmp_path):
    """Stage 1B must run from 01-raw.json; 02-normalized.json must not be required."""
    raw = {
        "handle": "filipelauar",
        "platform": "instagram",
        "_governance": {
            "source_id": "apify_instagram",
            "data_category": "PUBLIC_SCRAPE",
            "tos_compliant_at_ingest": True,
            "ingested_at": "2026-06-02T21:00:00Z",
            "gdpr_basis": "LEGITIMATE_INTERESTS",
            "subject_jurisdiction": "UNKNOWN",
            "retention_expires_at": "2027-06-02T21:00:00Z",
            "consent_record_id": None,
        },
        "raw_profile": {
            "handle": "filipelauar",
            "display_name": "Filipe Lauar",
            "website": "https://linktr.ee/vidacomia",
            "bio": "Podcast @podcast.lifewithai",
        },
        "raw_media": [],
    }
    (tmp_path / "01-raw.json").write_text(json.dumps(raw))
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        out = run("filipelauar", tmp_path, fast_only=True)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["handle"] == "filipelauar"


def test_compliance_block_has_required_keys(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
    data = json.loads((project_dir / "enrichment_map.json").read_text())
    c = data["compliance"]
    for key in ("osint_signals_present", "osint_signal_keys", "art9_risk_signals",
                "gdpr_basis", "requires_human_review", "opt_out_path"):
        assert key in c, f"Missing compliance key: {key}"


def test_schema_version_present(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
    data = json.loads((project_dir / "enrichment_map.json").read_text())
    assert data["schema_version"] == "enrichment_map/v1"


def test_limits_block_present(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
    data = json.loads((project_dir / "enrichment_map.json").read_text())
    lim = data["limits"]
    assert "actual_runs" in lim
    assert "limit_reached" in lim


def test_seeds_in_entity_pool(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
    data = json.loads((project_dir / "enrichment_map.json").read_text())
    types = {e["type"] for e in data["entity_pool"]}
    assert "handle" in types


def test_list_adapters_returns_19(project_dir):
    rows = list_adapters()
    assert len(rows) == 19
    ids = {r["adapter_id"] for r in rows}
    assert "linktree" in ids
    assert "maigret" in ids
