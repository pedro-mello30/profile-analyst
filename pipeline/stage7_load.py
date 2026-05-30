"""Stage 7 LOAD — upsert the dossier into Neo4j (spec 0002).

Reads the JSON artifacts produced by spec 0001 (02/03/05?/06) and idempotently upserts
the creator graph. Entities are MERGEd on natural keys; Signal/Score nodes are versioned
by ``run_id`` and prior-run versions are superseded each run (§6).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pipeline.compliance import assert_governance_complete, allow_noncompliant
from pipeline.graph import GraphSession, ensure_constraints, graph_config
from pipeline.graph import mappers

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "07-graph-load.schema.json"


# ── Cypher (all parameterized, batched via UNWIND) ─────────────────────────────

_MERGE_CREATOR = """
MERGE (c:Creator {user_id: $row.user_id})
ON CREATE SET c += $row, c.first_seen = $loaded_at
ON MATCH  SET c += $row, c.last_seen  = $loaded_at
"""

_MERGE_MEDIA = """
UNWIND $rows AS row
MATCH (c:Creator {user_id: $uid})
MERGE (m:Media {media_id: row.media_id})
ON CREATE SET m += row, m.first_seen = $loaded_at
ON MATCH  SET m += row, m.last_seen  = $loaded_at
MERGE (c)-[:HAS_MEDIA]->(m)
"""

_MERGE_COMMENTS = """
UNWIND $rows AS row
MATCH (m:Media {media_id: row.media_id})
MERGE (cm:Comment {comment_id: row.comment_id})
SET cm.text = row.text, cm.author_username = row.author_username, cm.timestamp = row.timestamp
MERGE (m)-[:HAS_COMMENT]->(cm)
WITH cm, row WHERE row.author_username IS NOT NULL
MERGE (u:User {username: row.author_username})
MERGE (cm)-[:FROM_USER]->(u)
"""

_MERGE_USERS = """
UNWIND $rows AS row
MERGE (u:User {username: row.username})
ON CREATE SET u.is_bot_score = row.is_bot_score
"""

_MERGE_SIGNALS = """
UNWIND $rows AS row
MATCH (c:Creator {user_id: $uid})
MERGE (sig:Signal {creator_user_id: $uid, name: row.name, run_id: $rid})
SET sig.value = row.value, sig.source = row.source, sig.confidence = row.confidence,
    sig.method = row.method, sig.art9_risk = row.art9_risk, sig.computed_at = row.computed_at,
    sig.run_id = $rid, sig.creator_user_id = $uid
MERGE (c)-[hs:HAS_SIGNAL]->(sig)
SET hs.weight = coalesce(row.confidence, 0.0)
"""

_MERGE_SCORES = """
UNWIND $rows AS row
MATCH (c:Creator {user_id: $uid})
MERGE (sc:Score {creator_user_id: $uid, type: row.type, run_id: $rid})
SET sc.value = row.value, sc.confidence = row.confidence, sc.signals = row.signals,
    sc.model_version = row.model_version, sc.created_at = row.created_at,
    sc.run_id = $rid, sc.status = row.status, sc.creator_user_id = $uid
MERGE (c)-[ct:CONTRIBUTED_TO]->(sc)
SET ct.weight = coalesce(row.confidence, 0.0)
"""

_MERGE_ASSOCIATIONS = """
UNWIND $rows AS row
MATCH (a:Creator {user_id: row.source_user_id})
MATCH (b:Creator {user_id: row.target_user_id})
MERGE (a)-[r:SHARES_AUDIENCE]->(b)
SET r.overlap_pct = row.overlap_pct
"""

_SUPERSEDE_SIGNALS = """
MATCH (c:Creator {user_id: $uid})-[:HAS_SIGNAL]->(s:Signal)
WHERE s.run_id <> $rid
WITH s
DETACH DELETE s
RETURN count(*) AS removed
"""

_SUPERSEDE_SCORES = """
MATCH (c:Creator {user_id: $uid})-[:CONTRIBUTED_TO]->(s:Score)
WHERE s.run_id <> $rid
WITH s
DETACH DELETE s
RETURN count(*) AS removed
"""


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as fh:
        return json.load(fh)


def _supersede_count(rows: list[dict]) -> int:
    return int(rows[0]["removed"]) if rows else 0


# ── orchestrator ────────────────────────────────────────────────────────────────

def run(
    handle: str,
    project_dir: Path,
    *,
    allow_noncompliant_flag: bool = False,
    run_id: str | None = None,
    loaded_at: str | None = None,
    session: GraphSession | None = None,
) -> Path:
    """Run Stage 7 for *handle*. Reads JSON artifacts, upserts Neo4j, writes the manifest.

    A live ``GraphSession`` can be injected (tests); otherwise one is opened from env config.
    """
    run_id = run_id or str(uuid.uuid4())
    loaded_at = loaded_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    normalized = _read_json(project_dir / "02-normalized.json")
    features = _read_json(project_dir / "03-features.json")
    dossier = _read_json(project_dir / "06-dossier.json")
    graph_doc = _read_json(project_dir / "05-graph.json")  # optional [v2]

    if normalized is None:
        raise FileNotFoundError(f"Stage 2 artifact not found: {project_dir / '02-normalized.json'}")
    if dossier is None:
        raise FileNotFoundError(f"Stage 6 artifact not found: {project_dir / '06-dossier.json'}")
    if features is None:
        raise FileNotFoundError(f"Stage 3 artifact not found: {project_dir / '03-features.json'}")

    # ── Compliance gate (C1) — runs before any DB connection ──────────────────
    gov = normalized.get("governance", {}) or {}
    if not (allow_noncompliant_flag or allow_noncompliant()):
        assert_governance_complete(gov)

    # ── Build batches (pure mappers) ──────────────────────────────────────────
    creator = mappers.creator_from_normalized(normalized)
    uid = creator["user_id"]
    media = mappers.media_from_normalized(normalized, features)
    comments = mappers.comments_from_media(normalized)
    users = mappers.users_from_comments(comments)
    signals = mappers.signals_from_features(features, run_id)
    scores = mappers.scores_from_dossier(dossier, run_id)
    assoc_edges, assoc_status = mappers.associations_from_graph(graph_doc)

    # ── Upsert ────────────────────────────────────────────────────────────────
    owns_session = session is None
    sess = session or GraphSession()
    if owns_session:
        sess.__enter__()
    try:
        ensure_constraints(sess)

        # Supersede prior-run signals/scores for this creator (§6, A7)
        superseded_signals = _supersede_count(sess.write(_SUPERSEDE_SIGNALS, uid=uid, rid=run_id))
        superseded_scores = _supersede_count(sess.write(_SUPERSEDE_SCORES, uid=uid, rid=run_id))

        sess.write(_MERGE_CREATOR, row=creator, loaded_at=loaded_at)
        if media:
            sess.write(_MERGE_MEDIA, rows=media, uid=uid, loaded_at=loaded_at)
        if users:
            sess.write(_MERGE_USERS, rows=users)
        if comments:
            sess.write(_MERGE_COMMENTS, rows=comments)
        if signals:
            sess.write(_MERGE_SIGNALS, rows=signals, uid=uid, rid=run_id)
        if scores:
            sess.write(_MERGE_SCORES, rows=scores, uid=uid, rid=run_id)
        if assoc_status == "loaded" and assoc_edges:
            sess.write(_MERGE_ASSOCIATIONS, rows=assoc_edges)
    finally:
        if owns_session:
            sess.__exit__(None, None, None)

    # ── Manifest ──────────────────────────────────────────────────────────────
    manifest = {
        "run_id": run_id,
        "handle": handle,
        "loaded_at": loaded_at,
        "neo4j_database": (session.database if session else graph_config()["database"]),
        "counts": {
            "nodes": {
                "Creator": 1,
                "Media": len(media),
                "Comment": len(comments),
                "User": len(users),
                "Signal": len(signals),
                "Score": len(scores),
            },
            "relationships": {
                "HAS_MEDIA": len(media),
                "HAS_COMMENT": len(comments),
                "FROM_USER": len(comments),
                "HAS_SIGNAL": len(signals),
                "CONTRIBUTED_TO": len(scores),
                "SHARES_AUDIENCE": len(assoc_edges) if assoc_status == "loaded" else 0,
            },
        },
        "associations": assoc_status,
        "superseded": {"signals": superseded_signals, "scores": superseded_scores},
    }

    jsonschema.validate(manifest, _load_schema())

    project_dir.mkdir(parents=True, exist_ok=True)
    out_path = project_dir / "07-load-manifest.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    os.replace(tmp_path, out_path)

    return out_path
