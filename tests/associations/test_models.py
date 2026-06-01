"""Unit tests for AssociationGraph / AssociationNeighbor / CommunitySummary (spec 0012 T5)."""
import pytest
from pydantic import ValidationError

from pipeline.models import (
    AssociationGraph,
    AssociationNeighbor,
    CommunitySummary,
    EgoCentrality,
    EgoView,
)

_GOV = {
    "source_id": "cohort-local",
    "data_category": "public_profile",
    "tos_compliant_at_ingest": True,
    "ingested_at": "2025-01-01T00:00:00Z",
    "gdpr_basis": "legitimate_interest",
    "subject_jurisdiction": "EU",
}

_EGO = EgoView(
    community_id=0,
    community_size=3,
    centrality=EgoCentrality(degree=0.5, pagerank=0.33, betweenness=0.25),
)

_NEIGHBOR = {
    "handle": "creator_b",
    "edge_type": "content_similar",
    "weight": 0.72,
    "method": "computed",
    "signals": ["shared niche: fitness"],
}

_COMMUNITY = {"community_id": 0, "size": 3, "members": ["a", "b", "c"], "art9_risk": False}


def test_association_graph_round_trips():
    graph = AssociationGraph(
        handle="creator_a",
        governance=_GOV,
        cohort_size=3,
        community_method="louvain",
        ego=_EGO,
        neighbors=[AssociationNeighbor(**_NEIGHBOR)],
        communities_summary=[CommunitySummary(**_COMMUNITY)],
    )
    assert graph.handle == "creator_a"
    assert graph.method_version == "v2a"
    assert graph.cohort_size == 3
    assert graph.neighbors[0].weight == 0.72


def test_neighbor_rejects_empty_signals():
    bad = {**_NEIGHBOR, "signals": []}
    with pytest.raises(ValidationError):
        AssociationNeighbor(**bad)


def test_neighbor_rejects_invalid_edge_type():
    bad = {**_NEIGHBOR, "edge_type": "follows"}
    with pytest.raises(ValidationError):
        AssociationNeighbor(**bad)


def test_cohort_size_minimum_2():
    with pytest.raises(ValidationError):
        AssociationGraph(
            handle="x",
            governance=_GOV,
            cohort_size=1,
            community_method="louvain",
            ego=_EGO,
            neighbors=[],
            communities_summary=[],
        )


def test_invalid_community_method():
    with pytest.raises(ValidationError):
        AssociationGraph(
            handle="x",
            governance=_GOV,
            cohort_size=2,
            community_method="girvan_newman",
            ego=_EGO,
            neighbors=[],
            communities_summary=[],
        )


def test_weight_bounds():
    for bad_w in (-0.1, 1.1):
        bad = {**_NEIGHBOR, "weight": bad_w}
        with pytest.raises(ValidationError):
            AssociationNeighbor(**bad)
