"""Acceptance tests for spec-0019 (AC1, AC8)."""
import pytest

from pipeline.enrichment.seeder import seed_from_raw, seed_from_discovery
from pipeline.enrichment.entity_pool import EntityPool
from pipeline.enrichment.engine import run_engine, EngineConfig

_DISCOVERY = {
    "discovered_accounts": [
        {
            "platform": "github",
            "handle": "creator-dev",
            "confidence": 0.85,
            "account_id": "gh-1",
            "attribution_chain": [{
                "adapter_id": "bio_parser",
                "from_entity_type": "instagram_handle",
                "from_entity_value": "creator",
                "relationship": "bio",
            }],
        },
        {
            "platform": "youtube",
            "handle": "Creator123Official",
            "confidence": 0.9,
            "account_id": "yt-1",
            "attribution_chain": [{
                "adapter_id": "bio_parser",
                "from_entity_type": "instagram_handle",
                "from_entity_value": "creator",
                "relationship": "bio",
            }],
        },
    ],
}


def test_ac1_discovery_github_seeded_at_depth1():
    """AC1: DiscoveredAccount in 00-discovery.json is eligible for enrichment at depth=1."""
    pool = EntityPool()
    seed_from_discovery(_DISCOVERY, pool)

    gh_entities = [e for e in pool.all_entities() if e.type == "github_handle"]
    assert len(gh_entities) >= 1, "github_handle not seeded from discovery"
    assert gh_entities[0].depth == 1, f"Expected depth=1, got {gh_entities[0].depth}"


def test_ac1_discovery_youtube_seeded_at_depth1():
    """AC1: YouTube DiscoveredAccount seeded as youtube_handle at depth=1."""
    pool = EntityPool()
    seed_from_discovery(_DISCOVERY, pool)

    yt_entities = [e for e in pool.all_entities() if e.type == "youtube_handle"]
    assert len(yt_entities) >= 1, "youtube_handle not seeded from discovery"
    assert yt_entities[0].depth == 1


def test_ac1_discovery_confidence_preserved():
    """AC1: confidence from DiscoveredAccount is preserved in seeded entity."""
    pool = EntityPool()
    seed_from_discovery(_DISCOVERY, pool)

    gh_entities = [e for e in pool.all_entities() if e.type == "github_handle"]
    assert gh_entities[0].confidence == pytest.approx(0.85, abs=0.01)


def test_ac8_no_discovery_produces_valid_result(tmp_path):
    """AC8: absent 00-discovery.json → engine produces valid (smaller) result."""
    pool, state, results = run_engine(
        {"handle": "creator"}, adapters=[],
        config=EngineConfig(), cache_dir=tmp_path,
    )
    # Engine ran successfully without discovery
    assert state.governance_report is not None
    assert pool.get("handle", "creator") is not None


def test_ac8_seed_from_discovery_none_is_noop():
    """AC8: seed_from_discovery(None) produces empty pool."""
    pool = EntityPool()
    seed_from_discovery(None, pool)
    assert len(pool) == 0


def test_ac8_seed_from_discovery_empty_dict_is_noop():
    """AC8: seed_from_discovery({}) produces empty pool."""
    pool = EntityPool()
    seed_from_discovery({}, pool)
    assert len(pool) == 0
