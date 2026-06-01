"""Stage 5 — Audience-Overlap Association Graph (v2a) (spec 0012 §3, T21).

run(handle, project_dir) is the single entry point:
  cohort discovery → edges → graph → communities → centrality → ego → gate
  → jsonschema validate → atomic write 05-graph.json

Idempotent: reads cohort 02/03 artifacts; writes only 05-graph.json.
Stage 5 is opt-in: --stage all never includes it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pipeline.associations.cohort import discover_cohort
from pipeline.associations.edges import content_similar_edges, collaborated_edges
from pipeline.associations.graph import build_graph, detect_communities, compute_centrality
from pipeline.associations.ego import build_ego_view
from pipeline.associations.gate import scan_community_art9, enforce_art22_signals

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "05-graph.schema.json"


def _load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def run(handle: str, project_dir: Path | str) -> Path:
    """Execute Stage 5 associations for ``handle``. Returns path to 05-graph.json."""
    project_dir = Path(project_dir)
    projects_root = project_dir.parent

    # ── 1. Cohort discovery ───────────────────────────────────────────────────
    cohort = discover_cohort(projects_root)
    handles = [p.handle for p in cohort]

    # ── 2. Edge families ──────────────────────────────────────────────────────
    content_edges = content_similar_edges(cohort, projects_root)
    collab_edges = collaborated_edges(cohort, projects_root)
    all_edges = content_edges + collab_edges

    # ── 3. Build graph ────────────────────────────────────────────────────────
    G = build_graph(all_edges, handles)

    # ── 4. Communities + centrality ───────────────────────────────────────────
    membership, community_method = detect_communities(G)
    centrality = compute_centrality(G)

    # ── 5. Art.9 community scan ───────────────────────────────────────────────
    community_art9 = scan_community_art9(membership, cohort)

    # ── 6. Ego view ───────────────────────────────────────────────────────────
    ego_dict, neighbors, communities_summary = build_ego_view(
        G, handle, membership, centrality, community_art9=community_art9,
    )

    # ── 7. Art.22 signals gate ────────────────────────────────────────────────
    enforce_art22_signals(neighbors)

    # ── 8. Governance from seed profile ──────────────────────────────────────
    seed_profile = next((p for p in cohort if p.handle == handle), cohort[0])
    governance = seed_profile.governance.model_dump()

    # ── 9. Build document ────────────────────────────────────────────────────
    doc = {
        "handle": handle,
        "method_version": "v2a",
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "governance": governance,
        "cohort_size": len(cohort),
        "community_method": community_method,
        "ego": ego_dict,
        "neighbors": neighbors,
        "communities_summary": communities_summary,
        "warnings": [],
    }

    # ── 10. Schema validate ───────────────────────────────────────────────────
    schema = _load_schema()
    jsonschema.validate(doc, schema)

    # ── 11. Atomic write ──────────────────────────────────────────────────────
    out_path = project_dir / "05-graph.json"
    tmp_fd, tmp_name = tempfile.mkstemp(dir=project_dir, prefix=".05-graph-")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp_name, out_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    return out_path
