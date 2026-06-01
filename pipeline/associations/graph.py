"""In-process graph build + community detection + centrality (spec 0012 §3, T14-T16).

Builds a networkx.Graph from the union of content_similar and collaborated edges.
Communities: Leiden (leidenalg, behind [associations] extra) with Louvain fallback.
Centrality: degree, pagerank, betweenness — all native networkx.
"""
from __future__ import annotations

import networkx as nx

try:
    import igraph as ig  # type: ignore
    import leidenalg  # type: ignore
    _HAS_LEIDEN = True
except ImportError:
    _HAS_LEIDEN = False


def build_graph(edges: list[dict], cohort_handles: list[str]) -> nx.Graph:
    """Build a networkx.Graph from the edge lists.

    Nodes are all cohort handles (sorted for determinism). Parallel edges
    (same u-v pair, different edge_type) are collapsed — both edge_types are
    retained in the ``edge_type`` attribute as a list.
    """
    G = nx.Graph()
    for h in sorted(cohort_handles):
        G.add_node(h)

    for e in edges:
        u, v = e["u"], e["v"]
        if G.has_edge(u, v):
            existing = G[u][v]
            existing_types = existing.get("edge_types", [existing.get("edge_type")])
            if e["edge_type"] not in existing_types:
                existing_types.append(e["edge_type"])
            G[u][v]["edge_types"] = existing_types
            G[u][v]["weight"] = max(existing.get("weight", 0), e["weight"])
            G[u][v]["signals"] = list(set(existing.get("signals", []) + e["signals"]))
        else:
            G.add_edge(u, v,
                       edge_type=e["edge_type"],
                       edge_types=[e["edge_type"]],
                       weight=e["weight"],
                       method=e["method"],
                       signals=e["signals"])
    return G


def detect_communities(G: nx.Graph, seed: int = 42) -> tuple[dict[str, int], str]:
    """Assign community IDs to nodes.

    Returns (node→community_id dict, method_name).
    Tries Leiden first; falls back to networkx Louvain.
    """
    nodes = sorted(G.nodes())

    if _HAS_LEIDEN and len(G.nodes()) >= 2:
        try:
            ig_graph = ig.Graph.from_networkx(G)
            part = leidenalg.find_partition(
                ig_graph,
                leidenalg.ModularityVertexPartition,
                seed=seed,
            )
            # Map back: igraph node index → handle
            ig_names = ig_graph.vs["_nx_name"]
            membership = {ig_names[i]: part.membership[i] for i in range(len(ig_names))}
            return membership, "leiden"
        except Exception:
            pass  # fall through to Louvain

    # Louvain fallback (deterministic with seed)
    communities = nx.community.louvain_communities(G, seed=seed)
    membership: dict[str, int] = {}
    for cid, community in enumerate(communities):
        for node in community:
            membership[node] = cid
    return membership, "louvain"


def compute_centrality(G: nx.Graph) -> dict[str, dict[str, float]]:
    """Return {handle: {degree, pagerank, betweenness}} for all nodes."""
    degree = nx.degree_centrality(G)
    try:
        pagerank = nx.pagerank(G, weight="weight") if G.number_of_edges() > 0 else {n: 0.0 for n in G}
    except ModuleNotFoundError:
        # scipy unavailable — fall back to power-iteration pagerank
        pagerank = nx.pagerank(G, weight=None) if G.number_of_edges() > 0 else {n: 0.0 for n in G}
    betweenness = nx.betweenness_centrality(G)
    result: dict[str, dict[str, float]] = {}
    for node in G.nodes():
        result[node] = {
            "degree": round(degree[node], 6),
            "pagerank": round(pagerank[node], 6),
            "betweenness": round(betweenness[node], 6),
        }
    return result
