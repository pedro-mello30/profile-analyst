"""Ego-centric view builder for Stage 5 (spec 0012 §3, T18).

Selects the seed node's community + centrality, ranks incident edges by weight,
and rolls up communities_summary with art9_risk flags.
"""
from __future__ import annotations

import networkx as nx

EGO_TOP_N: int = 10


def build_ego_view(
    G: nx.Graph,
    seed_handle: str,
    membership: dict[str, int],
    centrality: dict[str, dict[str, float]],
    *,
    community_art9: dict[int, bool] | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Return (ego dict, neighbors list, communities_summary list).

    ``community_art9`` maps community_id → art9_risk bool (from gate.py).
    """
    if seed_handle not in G:
        raise ValueError(f"Seed handle {seed_handle!r} not in graph")

    seed_community = membership.get(seed_handle, 0)
    community_members: dict[int, list[str]] = {}
    for handle, cid in membership.items():
        community_members.setdefault(cid, []).append(handle)

    community_size = len(community_members.get(seed_community, []))

    ego_dict = {
        "community_id": seed_community,
        "community_size": community_size,
        "centrality": centrality.get(seed_handle, {"degree": 0.0, "pagerank": 0.0, "betweenness": 0.0}),
    }

    # Neighbors: incident edges sorted by weight descending, top-N
    incident: list[dict] = []
    for neighbor in G.neighbors(seed_handle):
        edge_data = G[seed_handle][neighbor]
        # Prefer edge_type from edge_types list if collapsed
        edge_type = edge_data.get("edge_types", [edge_data.get("edge_type", "content_similar")])[0]
        incident.append({
            "handle": neighbor,
            "edge_type": edge_type,
            "weight": edge_data.get("weight", 0.0),
            "method": edge_data.get("method", "computed"),
            "signals": edge_data.get("signals", ["computed"]),
        })
    incident.sort(key=lambda e: e["weight"], reverse=True)
    neighbors = incident[:EGO_TOP_N]

    # Communities summary
    community_art9 = community_art9 or {}
    communities_summary: list[dict] = []
    for cid, members in sorted(community_members.items()):
        communities_summary.append({
            "community_id": cid,
            "size": len(members),
            "members": sorted(members),
            "art9_risk": community_art9.get(cid, False),
        })

    return ego_dict, neighbors, communities_summary
