"""Unit tests for ego view + compliance gate (spec 0012 T20)."""
import pytest
import networkx as nx

from pipeline.associations.ego import build_ego_view, EGO_TOP_N
from pipeline.associations.gate import (
    AssociationsGateError,
    enforce_art22_signals,
    scan_community_art9,
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


def _profile(handle: str, bio: str = "") -> Profile:
    return Profile(
        handle=handle,
        followers=1000,
        following=100,
        post_count=10,
        snapshot_at="2025-01-01T00:00:00Z",
        governance=_GOV,
        bio=bio or None,
    )


def _star_graph() -> tuple[nx.Graph, dict[str, int], dict[str, dict]]:
    """a-b, a-c, a-d — a is the hub."""
    from pipeline.associations.graph import build_graph, detect_communities, compute_centrality
    edges = [
        {"u": "seed", "v": "b", "edge_type": "content_similar", "weight": 0.9,
         "method": "computed", "signals": ["tag: fitness"]},
        {"u": "seed", "v": "c", "edge_type": "content_similar", "weight": 0.7,
         "method": "computed", "signals": ["tag: yoga"]},
        {"u": "seed", "v": "d", "edge_type": "collaborated", "weight": 0.5,
         "method": "computed", "signals": ["co-branded: x"]},
    ]
    G = build_graph(edges, ["seed", "b", "c", "d"])
    membership, _ = detect_communities(G)
    centrality = compute_centrality(G)
    return G, membership, centrality


def test_ego_view_correct_community_and_centrality():
    G, membership, centrality = _star_graph()
    ego, neighbors, communities = build_ego_view(G, "seed", membership, centrality)
    assert "community_id" in ego
    assert "centrality" in ego
    assert ego["centrality"]["degree"] > 0


def test_ego_top_n_neighbors_sorted_by_weight():
    G, membership, centrality = _star_graph()
    _, neighbors, _ = build_ego_view(G, "seed", membership, centrality)
    weights = [n["weight"] for n in neighbors]
    assert weights == sorted(weights, reverse=True)


def test_ego_top_n_capped():
    # Build a graph with more than EGO_TOP_N neighbors
    from pipeline.associations.graph import build_graph, detect_communities, compute_centrality
    handles = ["seed"] + [f"n{i}" for i in range(EGO_TOP_N + 3)]
    edges = [
        {"u": "seed", "v": h, "edge_type": "content_similar",
         "weight": 0.8, "method": "computed", "signals": ["x"]}
        for h in handles[1:]
    ]
    G = build_graph(edges, handles)
    membership, _ = detect_communities(G)
    centrality = compute_centrality(G)
    _, neighbors, _ = build_ego_view(G, "seed", membership, centrality)
    assert len(neighbors) <= EGO_TOP_N


def test_art9_community_flagged():
    profiles = [
        _profile("a", bio="lgbtq pride and queer activism"),
        _profile("b", bio="travel photography"),
    ]
    membership = {"a": 0, "b": 1}
    art9 = scan_community_art9(membership, profiles)
    assert art9[0] is True
    assert art9[1] is False


def test_non_art9_community_not_flagged():
    profiles = [
        _profile("a", bio="photography and travel"),
        _profile("b", bio="cooking and recipes"),
    ]
    membership = {"a": 0, "b": 0}
    art9 = scan_community_art9(membership, profiles)
    assert art9[0] is False


def test_art22_signals_enforcement_raises_on_empty():
    bad_neighbors = [{"handle": "b", "signals": []}]
    with pytest.raises(AssociationsGateError):
        enforce_art22_signals(bad_neighbors)


def test_art22_signals_enforcement_passes_with_signals():
    good_neighbors = [{"handle": "b", "signals": ["shared: fitness"]}]
    enforce_art22_signals(good_neighbors)  # must not raise
