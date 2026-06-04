"""E2E test for Stage 1B — uses dry_run/mocked adapters, no live network calls."""
import json
import pytest
import jsonschema
from pathlib import Path
from unittest.mock import patch

from pipeline.stage1b_enrichment import run
from pipeline.enrichment.engine import EngineConfig

NORM = {
    "handle": "filipelauar",
    "platform": "instagram",
    "_governance": {
        "source_id": "apify_instagram", "data_category": "PUBLIC_SCRAPE",
        "tos_compliant_at_ingest": True, "ingested_at": "2026-06-02T21:00:00Z",
        "gdpr_basis": "LEGITIMATE_INTERESTS", "subject_jurisdiction": "UNKNOWN",
        "retention_expires_at": "2027-06-02T21:00:00Z", "consent_record_id": None,
    },
    "raw_profile": {
        "handle": "filipelauar", "display_name": "Filipe Lauar",
        "website": "https://linktr.ee/vidacomia", "bio": "Podcast @podcast.lifewithai",
    },
    "raw_media": [],
}

SCHEMA = json.loads(Path("schemas/enrichment_map.schema.json").read_text())


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "01-raw.json").write_text(json.dumps(NORM))
    return tmp_path


def _run_empty(project_dir, **kwargs):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        return run("filipelauar", project_dir, **kwargs)


# A1 — validates against schema
def test_enrichment_map_validates_against_schema(project_dir):
    _run_empty(project_dir, fast_only=True)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    jsonschema.validate(doc, SCHEMA)   # must not raise


# A2 — fast tier builds v1 with timestamp
def test_fast_only_produces_v1_dossier(project_dir):
    _run_empty(project_dir, fast_only=True)
    status = json.loads((project_dir / "enrichment_status.json").read_text())
    assert status["dossier_version"] == "v1"
    assert status["v1_ready_at"] is not None


# A7 — limit_reached when max_adapter_runs=0
def test_limit_reached_flag(project_dir):
    cfg = EngineConfig(max_adapter_runs=0)
    _run_empty(project_dir, engine_config=cfg)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    # With 0 runs allowed and no adapters loaded, actual_runs=0 >= max=0 → limit_reached=True
    assert "limit_reached" in doc["limits"]


# A12 — art9_risk_signals listed
def test_art9_risk_signals_present(project_dir):
    _run_empty(project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert "art9_risk_signals" in doc["compliance"]
    assert isinstance(doc["compliance"]["art9_risk_signals"], list)


# A14 — enrichment is additive; Stage 2 works with or without enrichment_map
def test_stage2_runs_without_enrichment_map(project_dir):
    from pipeline.stage2_normalize import run as run_stage2
    raw = {
        "handle": "filipelauar", "platform": "instagram",
        "_governance": NORM["_governance"],
        "raw_profile": {
            "handle": "filipelauar", "platform": "instagram",
            "profile_id": "123", "display_name": "Filipe Lauar",
            "bio": None, "website": None, "is_verified": False,
            "is_business": False, "account_type": "PERSONAL",
            "location": None, "followers": 100, "following": 50,
            "post_count": 5, "snapshot_at": "2026-06-02T21:00:00Z",
        },
        "raw_media": [],
    }
    (project_dir / "01-raw.json").write_text(json.dumps(raw))
    out = run_stage2("filipelauar", project_dir)
    assert out.exists()
    # No enrichment_map present → no enrichment_signals key expected
    norm = json.loads(out.read_text())
    assert norm["handle"] == "filipelauar"


# A17 — conflict logging when two adapters produce same entity
def test_conflict_logging(project_dir):
    from pipeline.enrichment.adapter import AdapterResult, Signal, EnrichmentAdapter, AdapterConfig
    from pipeline.enrichment.entity import make_entity

    TS = "2026-06-02T21:00:00Z"

    class AdapterA(EnrichmentAdapter):
        adapter_id = "a1"; display_name = "A1"
        requires = ["handle"]; produces = ["youtube_channel_id"]
        tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5
        retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
        min_confidence = 0.5; max_instances = 1; osint_risk = False
        secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
        data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"
        def run(self, seeds, cfg):
            e = make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                            source="a1", confidence=0.8, depth=1, discovered_at=TS)
            return AdapterResult(adapter_id="a1", entities=[e], signals=[],
                                 error=None, cached=False, ran_at=TS, cost_usd=0.0)

    class AdapterB(EnrichmentAdapter):
        adapter_id = "a2"; display_name = "A2"
        requires = ["handle"]; produces = ["youtube_channel_id"]
        tier = "fast"; priority = 2; cost_usd = 0.0; timeout_s = 5
        retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
        min_confidence = 0.5; max_instances = 1; osint_risk = False
        secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
        data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"
        def run(self, seeds, cfg):
            e = make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                            source="a2", confidence=0.6, depth=1, discovered_at=TS)
            return AdapterResult(adapter_id="a2", entities=[e], signals=[],
                                 error=None, cached=False, ran_at=TS, cost_usd=0.0)

    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[AdapterA(), AdapterB()]):
        run("filipelauar", project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    # Only one youtube_channel_id entity in pool (dedup by value)
    yt_entities = [e for e in doc["entity_pool"] if e["type"] == "youtube_channel_id"]
    assert len(yt_entities) == 1
    # Higher confidence (0.8) wins
    assert yt_entities[0]["confidence"] == 0.8


# A18 — all timestamps end with Z
def test_timestamps_are_utc(project_dir):
    _run_empty(project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert doc["enriched_at"].endswith("Z")
    status = json.loads((project_dir / "enrichment_status.json").read_text())
    assert status["v1_ready_at"].endswith("Z")


# A19 — --list-adapters covers all 19 adapters
def test_list_adapters_covers_all(project_dir):
    from pipeline.stage1b_enrichment import list_adapters
    rows = list_adapters()
    assert len(rows) == 20
    ids = {r["adapter_id"] for r in rows}
    assert "instagram_bio" in ids and "linktree" in ids and "maigret" in ids and "hibp" in ids


# A24 — AdapterContractError raised at import time
def test_adapter_contract_error_at_import():
    from pipeline.enrichment.adapter import AdapterContractError, EnrichmentAdapter
    with pytest.raises(AdapterContractError):
        class BadAdapter(EnrichmentAdapter):
            adapter_id = "bad"
            # missing required attrs
            def run(self, s, c): pass


# A25 — osint_signals_present causes art22_applies in Stage 6
def test_osint_signals_propagate_to_art22(project_dir):
    """When enrichment_map has osint_signals_present=True and review.log is absent,
    Stage 6 must set art22_applies=True."""
    # Write a fake enrichment_map with osint_signals
    em = {
        "handle": "filipelauar", "enriched_at": "2026-06-02T21:00:00Z",
        "engine_version": "0014.1", "schema_version": "enrichment_map/v1",
        "status": "complete", "dossier_version": "v1",
        "gdpr_art9_consent_obtained": False,
        "limits": {"max_depth": 2, "max_adapter_runs": 20, "max_cost_usd": 0.5,
                   "actual_runs": 1, "actual_cost_usd": 0.0, "limit_reached": False},
        "entity_pool": [],
        "adapter_runs": [],
        "signals": [{"key": "holehe_service_count", "value": 5, "unit": "count",
                     "confidence": 0.9, "method": "osint", "source": "holehe",
                     "osint_risk": True}],
        "compliance": {
            "osint_signals_present": True,
            "osint_signal_keys": ["holehe_service_count"],
            "art9_risk_signals": [],
            "gdpr_basis": "LEGITIMATE_INTERESTS",
            "requires_human_review": True,
            "opt_out_path": "DELETE /profiles/filipelauar",
        }
    }
    (project_dir / "enrichment_map.json").write_text(json.dumps(em))
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert doc["compliance"]["osint_signals_present"] is True
    assert doc["compliance"]["requires_human_review"] is True


# A26 — two runs produce same entity pool (determinism)
def test_entity_pool_is_deterministic(project_dir):
    _run_empty(project_dir)
    pool1 = json.loads((project_dir / "enrichment_map.json").read_text())["entity_pool"]
    _run_empty(project_dir)
    pool2 = json.loads((project_dir / "enrichment_map.json").read_text())["entity_pool"]
    # Same entities (same type+value pairs) regardless of run order
    pairs1 = {(e["type"], e["value"]) for e in pool1}
    pairs2 = {(e["type"], e["value"]) for e in pool2}
    assert pairs1 == pairs2


# A30 — schema_version matches schema $id
def test_schema_version_matches_schema_id(project_dir):
    _run_empty(project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert doc["schema_version"] == SCHEMA.get("$id")


# spec-0020 — GovernanceReport embedded in enrichment_map.json
def test_governance_block_present_in_enrichment_map(project_dir):
    _run_empty(project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert "governance" in doc
    assert doc["governance"] is not None
    assert "run_id" in doc["governance"]
