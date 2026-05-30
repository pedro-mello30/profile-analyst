"""Stage 9 GDS — graph data-science algorithms over the Neo4j creator graph (spec 0004).

Runs Louvain (AL1), degree centrality (AL2), betweenness centrality (AL3),
Node Similarity / SHARES_AUDIENCE (AL4), and Adamic-Adar link prediction (AL5)
over a co-engagement projection of the whole graph (cross-handle). Results are
written back as Signal/Score nodes and SHARES_AUDIENCE / COLLABORATED_WITH edges.

Stage 9 is idempotent: each run gets a ``run_id`` (UUID); prior-run GDS artifacts
are superseded before new ones are written (§6). The in-memory projection is always
dropped in a ``finally`` block (A9).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pipeline.compliance import allow_noncompliant
from pipeline.graph import GraphSession, graph_config
from pipeline.graph.gds import assert_gds_available, drop_projection, project_co_engagement
from pipeline.graph import gds_algorithms as algo
from pipeline.graph import gds_writeback as wb

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "11-gds.schema.json"
_FRAUD_MODEL_VERSION = "gds-fraud-v1"
_ART9_PROXY_WARNING = (
    "community_id must not be used as a proxy for a protected attribute "
    "(GDPR Art. 9). Communities that correlate with Art. 9 signal clusters are "
    "flagged art9_risk=true on the Signal node."
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


def _art9_user_ids(session, run_id: str) -> list[str]:
    """Return user_ids of Creators that have any art9_risk Signal in the current run."""
    rows = session.read(
        "MATCH (c:Creator)-[:HAS_SIGNAL]->(s:Signal {art9_risk: true}) "
        "WHERE s.run_id = $run_id OR s.run_id IS NOT NULL "
        "RETURN DISTINCT c.user_id AS user_id",
        run_id=run_id,
    )
    return [r["user_id"] for r in rows if r["user_id"]]


def run(
    handle: str,
    project_dir: Path | None = None,
    *,
    allow_noncompliant_flag: bool = False,
    run_id: str | None = None,
    computed_at: str | None = None,
    session: GraphSession | None = None,
) -> Path:
    """Run Stage 9 GDS for *handle*.

    The algorithms run over the whole graph (cross-handle); ``handle`` scopes only
    which project dir receives the ``09-gds-manifest.json``.

    A live ``GraphSession`` can be injected (tests); otherwise one is opened from env.
    """
    run_id = run_id or str(uuid.uuid4())
    computed_at = computed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── config from environment (§9) ──────────────────────────────────────────
    graph_name = os.environ.get("GDS_GRAPH_NAME", "profile-analyst")
    similarity_cutoff = _env_float("GDS_SIMILARITY_CUTOFF", 0.10)
    topk_similarity = _env_int("GDS_TOPK_SIMILARITY", 10)
    linkpred_topn = _env_int("GDS_LINKPRED_TOPN", 10)
    louvain_max_levels = _env_int("GDS_LOUVAIN_MAX_LEVELS", 10)
    pod_max = _env_int("GDS_POD_MAX", 8)
    fraud_weights = algo.parse_weights(os.environ.get("GDS_FRAUD_WEIGHTS"))
    gate_gov = not (allow_noncompliant_flag or allow_noncompliant())

    # ── output path ───────────────────────────────────────────────────────────
    if project_dir is None:
        project_dir = Path("projects") / handle
    project_dir.mkdir(parents=True, exist_ok=True)
    out_path = project_dir / "09-gds-manifest.json"

    owns_session = session is None
    sess = session or GraphSession()
    if owns_session:
        sess.__enter__()
    try:
        # A8 — fail fast if GDS plugin absent
        gds_version_str = assert_gds_available(sess)

        # A9 / §6 — drop any stale projection, rebuild from current graph
        drop_projection(sess, graph_name)
        project_co_engagement(sess, graph_name, gate_governance=gate_gov)

        # A7 — supersede prior-run GDS artifacts
        superseded = wb.supersede_prior_run(sess, run_id)

        # ── AL1 Louvain ───────────────────────────────────────────────────────
        communities = algo.run_louvain(sess, graph_name, max_levels=louvain_max_levels)

        # ── AL2 Degree centrality ─────────────────────────────────────────────
        degree = algo.run_degree(sess, graph_name)

        # ── AL3 Betweenness centrality ────────────────────────────────────────
        betweenness = algo.run_betweenness(sess, graph_name)

        # ── AL4 Node Similarity → SHARES_AUDIENCE edges ───────────────────────
        similarity_edges = algo.run_node_similarity(
            sess, graph_name, top_k=topk_similarity, cutoff=similarity_cutoff
        )

        # ── AL5 Link prediction → COLLABORATED_WITH edges ────────────────────
        link_edges = algo.run_link_prediction(sess, top_n=linkpred_topn)

        # ── Art. 9 proxy caution (C2) ─────────────────────────────────────────
        art9_users = _art9_user_ids(sess, run_id)
        art9_coms = algo.art9_communities_for(communities, art9_users)

        # ── Build signal rows ─────────────────────────────────────────────────
        signal_rows = algo.build_signal_rows(
            communities, degree, betweenness, art9_communities=art9_coms
        )

        # ── fraud_risk blend ──────────────────────────────────────────────────
        pod = algo.pod_density(communities, pod_max=pod_max)
        fraud_scores = algo.compute_fraud_scores(pod, betweenness, degree, fraud_weights)
        signal_weights = {
            "community_id": fraud_weights.get("pod", 0.0),
            "betweenness_centrality": fraud_weights.get("btw", 0.0),
            "degree_centrality": fraud_weights.get("deg", 0.0),
        }

        # ── Write back ────────────────────────────────────────────────────────
        n_signals = wb.write_signals(sess, signal_rows, run_id, computed_at)
        n_audience = wb.write_shares_audience(sess, similarity_edges, run_id)
        n_collab = wb.write_collaborated_with(sess, link_edges, run_id)
        n_scores = wb.write_fraud_scores(
            sess, fraud_scores, signal_weights, run_id, computed_at, _FRAUD_MODEL_VERSION
        )

    finally:
        # A9 — always drop the in-memory projection
        try:
            if owns_session or session is not None:
                drop_projection(sess, graph_name)
        except Exception:
            pass
        if owns_session:
            sess.__exit__(None, None, None)

    # ── Manifest ──────────────────────────────────────────────────────────────
    manifest = {
        "run_id": run_id,
        "handle": handle,
        "graph_name": graph_name,
        "gds_version": gds_version_str,
        "computed_at": computed_at,
        "scope": "whole-graph",
        "algorithms": ["louvain", "degree_centrality", "betweenness_centrality",
                       "node_similarity", "link_prediction"],
        "counts": {
            "signals": {
                "community_id": sum(1 for r in signal_rows if r["name"] == "community_id"),
                "degree_centrality": sum(1 for r in signal_rows if r["name"] == "degree_centrality"),
                "betweenness_centrality": sum(1 for r in signal_rows if r["name"] == "betweenness_centrality"),
            },
            "edges": {
                "SHARES_AUDIENCE": n_audience,
                "COLLABORATED_WITH": n_collab,
            },
            "scores": n_scores,
        },
        "fraud": {
            "model_version": _FRAUD_MODEL_VERSION,
            "weights": fraud_weights,
            "normalization": "min-max",
        },
        "superseded": superseded,
        "art9_proxy_warning": _ART9_PROXY_WARNING,
        "data_egress": "none",
    }

    jsonschema.validate(manifest, _load_schema())

    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    os.replace(tmp_path, out_path)

    return out_path
