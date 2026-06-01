"""Unit tests for association edge families (spec 0012 T13)."""
import json
from pathlib import Path

import pytest

from pipeline.associations.edges import (
    CONTENT_SIM_THRESHOLD,
    content_similar_edges,
    collaborated_edges,
)
from pipeline.models import MediaItem, Profile

_GOV = {
    "source_id": "sample",
    "data_category": "SAMPLE",
    "tos_compliant_at_ingest": True,
    "ingested_at": "2025-01-01T00:00:00Z",
    "gdpr_basis": "LEGITIMATE_INTERESTS",
    "subject_jurisdiction": "EU",
    "retention_expires_at": "2025-10-01T00:00:00Z",
}


def _profile(handle: str, hashtags: list[str] | None = None, mentions: list[str] | None = None,
             paid_partner: str | None = None) -> Profile:
    media = []
    if hashtags or mentions or paid_partner:
        media.append(MediaItem(
            media_id="m1",
            media_type="IMAGE",
            posted_at="2025-01-01T00:00:00Z",
            hashtags=hashtags or [],
            mentions=mentions or [],
            paid_partner_handle=paid_partner,
        ))
    return Profile(
        handle=handle,
        followers=1000,
        following=100,
        post_count=10,
        snapshot_at="2025-01-01T00:00:00Z",
        governance=_GOV,
        media=media,
    )


def _write_features(tmp_path: Path, handle: str, niche: str) -> None:
    (tmp_path / handle).mkdir(exist_ok=True)
    feat = {
        "profile_handle": handle,
        "computed_at": "2025-01-01T00:00:00Z",
        "features": [{"feature_id": "niche", "value": niche, "confidence": 0.9,
                       "method": "llm", "art9_risk": False, "signals": ["x"]}]
    }
    (tmp_path / handle / "03-features.json").write_text(json.dumps(feat))


# ── content_similar tests ─────────────────────────────────────────────────────

def test_high_overlap_creates_edge(tmp_path):
    # 4 shared out of 5 total → Jaccard = 4/5 = 0.8, well above 0.60 threshold
    pa = _profile("creator_a", hashtags=["fitness", "wellness", "workout", "yoga"])
    pb = _profile("creator_b", hashtags=["fitness", "wellness", "workout", "yoga", "pilates"])
    edges = content_similar_edges([pa, pb], tmp_path)
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "content_similar"
    assert edges[0]["weight"] >= CONTENT_SIM_THRESHOLD
    assert len(edges[0]["signals"]) >= 1


def test_no_overlap_creates_no_edge(tmp_path):
    pa = _profile("creator_a", hashtags=["cooking", "pasta", "italy"])
    pb = _profile("creator_b", hashtags=["gaming", "esports", "twitch"])
    edges = content_similar_edges([pa, pb], tmp_path)
    assert len(edges) == 0


def test_identical_tokens_max_similarity(tmp_path):
    tags = ["fitness", "wellness", "workout", "yoga", "health"]
    pa = _profile("creator_a", hashtags=tags)
    pb = _profile("creator_b", hashtags=tags)
    edges = content_similar_edges([pa, pb], tmp_path)
    assert len(edges) == 1
    assert edges[0]["weight"] >= CONTENT_SIM_THRESHOLD


def test_content_similar_signals_non_empty(tmp_path):
    pa = _profile("creator_a", hashtags=["fitness", "wellness"])
    pb = _profile("creator_b", hashtags=["fitness", "yoga"])
    edges = content_similar_edges([pa, pb], tmp_path)
    if edges:
        assert len(edges[0]["signals"]) >= 1


# ── collaborated tests ────────────────────────────────────────────────────────

def test_mutual_mention_creates_edge(tmp_path):
    pa = _profile("creator_a", mentions=["@creator_b"])
    pb = _profile("creator_b", mentions=["@creator_a"])
    edges = collaborated_edges([pa, pb], tmp_path)
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "collaborated"
    assert any("mentions" in s for s in edges[0]["signals"])


def test_co_sponsored_brand_creates_edge(tmp_path):
    pa = _profile("creator_a", paid_partner="brand_x")
    pb = _profile("creator_b", paid_partner="brand_x")
    edges = collaborated_edges([pa, pb], tmp_path)
    assert len(edges) == 1
    assert any("co-sponsored" in s for s in edges[0]["signals"])


def test_no_collaboration_no_edge(tmp_path):
    pa = _profile("creator_a")
    pb = _profile("creator_b")
    edges = collaborated_edges([pa, pb], tmp_path)
    assert len(edges) == 0


def test_disjoint_mentions_no_edge(tmp_path):
    pa = _profile("creator_a", mentions=["@someone_else"])
    pb = _profile("creator_b", mentions=["@yet_another"])
    edges = collaborated_edges([pa, pb], tmp_path)
    assert len(edges) == 0


def test_all_edges_have_non_empty_signals(tmp_path):
    pa = _profile("creator_a", mentions=["@creator_b"], hashtags=["fitness"])
    pb = _profile("creator_b", mentions=["@creator_a"], hashtags=["fitness"])
    for fn in [content_similar_edges, collaborated_edges]:
        edges = fn([pa, pb], tmp_path)
        for e in edges:
            assert len(e["signals"]) >= 1, f"{fn.__name__}: signals must be non-empty"
