"""GDS algorithm runners (AL1–AL5) + the pure fraud-risk blend math (spec 0004 §5).

The functions at the top are **pure** (no driver) and unit-testable without a database:
weight parsing, min-max normalization, community sizing, pod-density, and the
``fraud_risk`` linear blend. The stream runners below take an open ``GraphSession``.
"""
from __future__ import annotations

import math
from typing import Iterable

# ── pure: config + math ─────────────────────────────────────────────────────────

DEFAULT_FRAUD_WEIGHTS = {"pod": 0.5, "btw": 0.3, "deg": 0.2}


def parse_weights(spec: str | None) -> dict[str, float]:
    """Parse ``"pod:0.5,btw:0.3,deg:0.2"`` into a dict. Falls back to defaults."""
    if not spec:
        return dict(DEFAULT_FRAUD_WEIGHTS)
    out: dict[str, float] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition(":")
        out[key.strip()] = float(value)
    return out or dict(DEFAULT_FRAUD_WEIGHTS)


def normalize_minmax(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalize a ``user_id -> value`` map into ``[0, 1]`` (OQ3 default).

    Stable on small/degenerate graphs: when all values are equal (or empty) every
    entry maps to ``0.0`` rather than dividing by zero.
    """
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi == lo:
        return {k: 0.0 for k in values}
    span = hi - lo
    return {k: (v - lo) / span for k, v in values.items()}


def community_sizes(communities: dict[str, int]) -> dict[int, int]:
    """Map ``community_id -> member count`` from a ``user_id -> community_id`` map."""
    sizes: dict[int, int] = {}
    for cid in communities.values():
        sizes[cid] = sizes.get(cid, 0) + 1
    return sizes


def pod_density(communities: dict[str, int], *, pod_max: int = 8) -> dict[str, float]:
    """Per-creator pod-density signal: tight small communities score higher.

    A creator in a community of size ``s`` (``2 <= s <= pod_max``) gets ``1/s`` — a
    2-member pod (most suspicious) scores 0.5, an 8-member pod ~0.125. Singletons
    (``s == 1``) and communities larger than *pod_max* score 0.0.
    """
    sizes = community_sizes(communities)
    out: dict[str, float] = {}
    for user_id, cid in communities.items():
        size = sizes.get(cid, 1)
        out[user_id] = (1.0 / size) if 2 <= size <= pod_max else 0.0
    return out


def compute_fraud_scores(
    pod: dict[str, float],
    betweenness: dict[str, float],
    degree: dict[str, float],
    weights: dict[str, float],
) -> dict[str, float]:
    """Linear-blend ``fraud_risk`` per creator from normalized signals (§5.1, G4)."""
    npod = normalize_minmax(pod)
    nbtw = normalize_minmax(betweenness)
    ndeg = normalize_minmax(degree)
    users: set[str] = set(npod) | set(nbtw) | set(ndeg)
    w_pod = weights.get("pod", 0.0)
    w_btw = weights.get("btw", 0.0)
    w_deg = weights.get("deg", 0.0)
    out: dict[str, float] = {}
    for u in users:
        out[u] = round(
            w_pod * npod.get(u, 0.0) + w_btw * nbtw.get(u, 0.0) + w_deg * ndeg.get(u, 0.0),
            6,
        )
    return out


def build_signal_rows(
    communities: dict[str, int],
    degree: dict[str, float],
    betweenness: dict[str, float],
    art9_communities: Iterable[int] = (),
) -> list[dict]:
    """Build GDS Signal write-back rows (community_id / degree / betweenness).

    ``community_id`` Signals are flagged ``art9_risk:true`` when their community is in
    *art9_communities* (C2 proxy caution); centrality Signals are never art9-flagged.
    All carry ``confidence: 1.0`` (deterministic, computed).
    """
    flagged = set(art9_communities)
    rows: list[dict] = []
    for user_id, cid in communities.items():
        rows.append({
            "user_id": user_id, "name": "community_id", "value": int(cid),
            "confidence": 1.0, "art9_risk": cid in flagged,
        })
    for user_id, score in degree.items():
        rows.append({
            "user_id": user_id, "name": "degree_centrality", "value": round(float(score), 6),
            "confidence": 1.0, "art9_risk": False,
        })
    for user_id, score in betweenness.items():
        rows.append({
            "user_id": user_id, "name": "betweenness_centrality", "value": round(float(score), 6),
            "confidence": 1.0, "art9_risk": False,
        })
    return rows


def normalize_edge_probabilities(edges: list[dict], key: str = "probability") -> list[dict]:
    """Min-max normalize an edge-list weight into ``[0, 1]`` (link-pred probabilities)."""
    if not edges:
        return []
    raw = {i: float(e[key]) for i, e in enumerate(edges)}
    norm = normalize_minmax(raw)
    out = []
    for i, e in enumerate(edges):
        e = dict(e)
        e[key] = round(norm[i], 6)
        out.append(e)
    return out


# ── GDS stream runners (require an open GraphSession) ─────────────────────────────

def run_louvain(session, graph_name: str, *, max_levels: int = 10) -> dict[str, int]:
    """AL1 — Louvain communities (weighted). Returns ``user_id -> community_id``."""
    rows = session.read(
        "CALL gds.louvain.stream($graph_name, "
        "{relationshipWeightProperty: 'weight', maxLevels: $max_levels}) "
        "YIELD nodeId, communityId "
        "RETURN gds.util.asNode(nodeId).user_id AS user_id, communityId AS community_id",
        graph_name=graph_name, max_levels=max_levels,
    )
    return {r["user_id"]: int(r["community_id"]) for r in rows}


def run_degree(session, graph_name: str) -> dict[str, float]:
    """AL2 — weighted degree centrality. Returns ``user_id -> score``."""
    rows = session.read(
        "CALL gds.degree.stream($graph_name, {relationshipWeightProperty: 'weight'}) "
        "YIELD nodeId, score "
        "RETURN gds.util.asNode(nodeId).user_id AS user_id, score",
        graph_name=graph_name,
    )
    return {r["user_id"]: float(r["score"]) for r in rows}


def run_betweenness(session, graph_name: str) -> dict[str, float]:
    """AL3 — betweenness centrality. Returns ``user_id -> score``."""
    rows = session.read(
        "CALL gds.betweenness.stream($graph_name) "
        "YIELD nodeId, score "
        "RETURN gds.util.asNode(nodeId).user_id AS user_id, score",
        graph_name=graph_name,
    )
    return {r["user_id"]: float(r["score"]) for r in rows}


def run_node_similarity(
    session, graph_name: str, *, top_k: int = 10, cutoff: float = 0.10
) -> list[dict]:
    """AL4 — Node Similarity (Jaccard). Returns SHARES_AUDIENCE edge rows."""
    rows = session.read(
        "CALL gds.nodeSimilarity.stream($graph_name, "
        "{topK: $top_k, similarityCutoff: $cutoff}) "
        "YIELD node1, node2, similarity "
        "RETURN gds.util.asNode(node1).user_id AS a, "
        "gds.util.asNode(node2).user_id AS b, similarity",
        graph_name=graph_name, top_k=top_k, cutoff=cutoff,
    )
    return [
        {"a": r["a"], "b": r["b"], "overlap_pct": round(float(r["similarity"]), 6)}
        for r in rows
    ]


# AL5 — topological Adamic-Adar over shared commenters, computed in plain Cypher
# (no trained model, N3). Score(a,b) = Σ_{shared commenter u} 1/ln(deg(u)), where
# deg(u) is the number of distinct Creators u engages with.
_LINK_PREDICTION = """
MATCH (a:Creator)-[:HAS_MEDIA]->(:Media)-[:HAS_COMMENT]->(:Comment)-[:FROM_USER]->(u:User)
MATCH (b:Creator)-[:HAS_MEDIA]->(:Media)-[:HAS_COMMENT]->(:Comment)-[:FROM_USER]->(u)
WHERE elementId(a) < elementId(b) AND NOT (a)-[:COLLABORATED_WITH]->(b)
WITH a, b, u
MATCH (u)<-[:FROM_USER]-(:Comment)<-[:HAS_COMMENT]-(:Media)<-[:HAS_MEDIA]-(cc:Creator)
WITH a, b, u, count(DISTINCT cc) AS udeg
WHERE udeg > 1
WITH a, b, sum(1.0 / log(udeg)) AS aa
WHERE aa > 0
RETURN a.user_id AS a, b.user_id AS b, aa AS probability
ORDER BY aa DESC
"""


def run_link_prediction(session, *, top_n: int = 10) -> list[dict]:
    """AL5 — Adamic-Adar link prediction; keeps the global top-N candidate pairs."""
    rows = session.read(_LINK_PREDICTION)
    pairs = [{"a": r["a"], "b": r["b"], "probability": float(r["probability"])} for r in rows]
    pairs = pairs[: max(top_n, 0)]
    return normalize_edge_probabilities(pairs)


def art9_communities_for(communities: dict[str, int], art9_user_ids: Iterable[str]) -> set[int]:
    """Communities (C2) that contain at least one creator with an Art. 9 signal."""
    flagged_users = set(art9_user_ids)
    return {cid for uid, cid in communities.items() if uid in flagged_users}
