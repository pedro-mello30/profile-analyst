"""Unit tests for graph build + community detection + centrality (spec 0012 T17)."""
import sys
from unittest.mock import patch

import pytest
import networkx as nx

from pipeline.associations.graph import build_graph, detect_communities, compute_centrality


def _make_edges(pairs: list[tuple[str, str]], edge_type: str = "content_similar") -> list[dict]:
    return [
        {
            "u": u, "v": v,
            "edge_type": edge_type,
            "weight": 0.8,
            "method": "computed",
            "signals": [f"shared: x"],
        }
        for u, v in pairs
    ]


def test_build_graph_all_nodes_present():
    handles = ["a", "b", "c"]
    edges = _make_edges([("a", "b")])
    G = build_graph(edges, handles)
    assert set(G.nodes()) == {"a", "b", "c"}


def test_build_graph_edge_present():
    G = build_graph(_make_edges([("a", "b")]), ["a", "b"])
    assert G.has_edge("a", "b")


def test_build_graph_collapses_parallel_edges():
    edges = _make_edges([("a", "b")], "content_similar") + _make_edges([("a", "b")], "collaborated")
    G = build_graph(edges, ["a", "b"])
    assert G.number_of_edges() == 1
    assert set(G["a"]["b"]["edge_types"]) == {"content_similar", "collaborated"}


def test_two_cluster_graph_yields_two_communities():
    # Two disconnected cliques → two communities
    edges = _make_edges([("a", "b"), ("b", "c"), ("a", "c")]) + \
            _make_edges([("d", "e"), ("e", "f"), ("d", "f")])
    G = build_graph(edges, ["a", "b", "c", "d", "e", "f"])
    membership, method = detect_communities(G)
    comm_ids = set(membership.values())
    assert len(comm_ids) == 2


def test_community_method_recorded():
    edges = _make_edges([("a", "b"), ("b", "c")])
    G = build_graph(edges, ["a", "b", "c"])
    _, method = detect_communities(G)
    assert method in {"leiden", "louvain"}


def test_louvain_fallback_when_leidenalg_blocked(monkeypatch):
    import pipeline.associations.graph as gmod
    monkeypatch.setattr(gmod, "_HAS_LEIDEN", False)

    edges = _make_edges([("a", "b"), ("b", "c")])
    G = build_graph(edges, ["a", "b", "c"])
    _, method = detect_communities(G)
    assert method == "louvain"


def test_centrality_keys_present():
    edges = _make_edges([("a", "b"), ("b", "c")])
    G = build_graph(edges, ["a", "b", "c"])
    centrality = compute_centrality(G)
    for node in ["a", "b", "c"]:
        assert "degree" in centrality[node]
        assert "pagerank" in centrality[node]
        assert "betweenness" in centrality[node]


def test_hub_has_higher_betweenness():
    # b is the bridge between a-b-c chain
    edges = _make_edges([("a", "b"), ("b", "c")])
    G = build_graph(edges, ["a", "b", "c"])
    centrality = compute_centrality(G)
    assert centrality["b"]["betweenness"] > centrality["a"]["betweenness"]
