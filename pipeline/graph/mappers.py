"""Pure JSON-artifact → graph-batch mappers (spec 0002 §5, §6).

No I/O, no driver — every function takes plain dicts (parsed artifacts) and returns
plain dicts/lists ready to be fed to parameterized ``UNWIND`` Cypher. Fully unit-testable
without a database.

Neo4j can only store scalars and lists of scalars as properties, so non-scalar feature
values (e.g. lists of objects) are JSON-encoded via :func:`_safe_value`.
"""
from __future__ import annotations

import json
from typing import Any


# ── value coercion ─────────────────────────────────────────────────────────────

def _is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


def _safe_value(value: Any) -> Any:
    """Return a Neo4j-storable representation of *value*.

    Scalars and lists of scalars pass through unchanged; anything else (nested maps,
    lists of objects) is JSON-encoded into a string so it can live on a property.
    """
    if _is_scalar(value):
        return value
    if isinstance(value, list) and all(_is_scalar(item) for item in value):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


# ── entities ─────────────────────────────────────────────────────────────────

def creator_from_normalized(normalized: dict) -> dict:
    """Creator node props (natural key ``user_id``) incl. governance metadata (§5.1, C1)."""
    gov = normalized.get("governance", {}) or {}
    user_id = normalized.get("profile_id") or normalized.get("handle")
    return {
        "user_id": user_id,
        "username": normalized.get("handle"),
        "followers_count": normalized.get("followers"),
        "following_count": normalized.get("following"),
        "media_count": normalized.get("post_count"),
        "verified": normalized.get("is_verified"),
        "account_type": normalized.get("account_type"),
        # governance (C1) — load MUST fail upstream if these are missing
        "gdpr_basis": gov.get("gdpr_basis"),
        "subject_jurisdiction": gov.get("subject_jurisdiction"),
        "tos_compliant_at_ingest": gov.get("tos_compliant_at_ingest"),
        "source_id": gov.get("source_id"),
    }


def _ftc_status_for(media: dict, sponsored_ids: set[str], undisclosed_ids: set[str]) -> str:
    """Per-Media FTC disclosure status derived from Stage 3 feature lists (C4)."""
    mid = media.get("media_id")
    if mid in undisclosed_ids:
        return "undisclosed"
    if mid in sponsored_ids or media.get("is_paid_partnership"):
        return "disclosed"
    return "none"


def _feature_index(features_doc: dict | None) -> dict[str, dict]:
    if not features_doc:
        return {}
    return {f["feature_id"]: f for f in features_doc.get("features", [])}


def media_from_normalized(normalized: dict, features_doc: dict | None = None) -> list[dict]:
    """Media nodes (natural key ``media_id``), each carrying ``ftc_disclosure_status``."""
    feats = _feature_index(features_doc)
    sponsored_ids = set(feats.get("sponsored_posts", {}).get("value", []) or [])
    undisclosed_ids = set(feats.get("likely_sponsored_undisclosed", {}).get("value", []) or [])

    rows: list[dict] = []
    for m in normalized.get("media", []) or []:
        rows.append({
            "media_id": m.get("media_id"),
            "permalink": m.get("permalink"),
            "timestamp": m.get("posted_at"),
            "media_type": m.get("media_type"),
            "caption_text": m.get("caption"),
            "ftc_disclosure_status": _ftc_status_for(m, sponsored_ids, undisclosed_ids),
        })
    return rows


def comments_from_media(normalized: dict) -> list[dict]:
    """Comment nodes from any per-media comment objects.

    The v1 SampleAdapter records a comment *count* (int), not comment objects, so this
    returns ``[]`` for v1 data. When an adapter supplies a list of comment objects, each
    is mapped to a Comment node tagged with its parent ``media_id``.
    """
    rows: list[dict] = []
    for m in normalized.get("media", []) or []:
        comments = m.get("comments")
        if not isinstance(comments, list):
            continue
        for c in comments:
            rows.append({
                "comment_id": c.get("comment_id") or c.get("id"),
                "text": c.get("text"),
                "author_username": c.get("author_username") or c.get("author"),
                "timestamp": c.get("timestamp") or c.get("posted_at"),
                "media_id": m.get("media_id"),
            })
    return rows


def users_from_comments(comments: list[dict]) -> list[dict]:
    """Unique User nodes (natural key ``username``) from comment authors."""
    seen: dict[str, dict] = {}
    for c in comments:
        uname = c.get("author_username")
        if uname and uname not in seen:
            seen[uname] = {"username": uname, "is_bot_score": None}
    return list(seen.values())


# ── signals & scores (versioned by run_id) ─────────────────────────────────────

def signals_from_features(features_doc: dict, run_id: str) -> list[dict]:
    """Signal nodes from the feature catalog (§5.1, C2).

    Each carries ``confidence``, ``method``, ``art9_risk``, ``source`` and ``computed_at``.
    The ``HAS_SIGNAL`` edge weight is derived from ``confidence`` in the loader.
    """
    computed_at = features_doc.get("computed_at")
    rows: list[dict] = []
    for f in features_doc.get("features", []):
        source = ", ".join(f.get("signals", []) or []) or None
        rows.append({
            "name": f["feature_id"],
            "value": _safe_value(f.get("value")),
            "source": source,
            "confidence": f.get("confidence"),
            "method": f.get("method"),
            "art9_risk": bool(f.get("art9_risk", False)),
            "computed_at": computed_at,
            "run_id": run_id,
        })
    return rows


def scores_from_dossier(dossier_doc: dict, run_id: str) -> list[dict]:
    """Score nodes from the dossier (§5.1, C3).

    The raw textual ``signals[]`` chain from Stage 6 is preserved on the node for Art. 22
    audit fidelity (G3); structured signal reconstruction is via the Signal nodes (AQ1).
    """
    model_version = dossier_doc.get("provenance", {}).get("pipeline_version")
    created_at = dossier_doc.get("generated_at")
    rows: list[dict] = []
    for stype, s in (dossier_doc.get("scores", {}) or {}).items():
        rows.append({
            "type": stype,
            "value": s.get("value"),
            "confidence": s.get("confidence"),
            "signals": list(s.get("signals", []) or []),
            "model_version": model_version,
            "created_at": created_at,
            "run_id": run_id,
            "status": "active",
        })
    return rows


def contributions(score_rows: list[dict]) -> list[dict]:
    """CONTRIBUTED_TO {weight} edge specs (Creator→Score); weight from score confidence."""
    return [
        {"type": r["type"], "weight": r.get("confidence") or 0.0}
        for r in score_rows
    ]


# ── associations (v2; deferred when 05-graph.json absent) ───────────────────────

def associations_from_graph(graph_doc: dict | None) -> tuple[list[dict], str]:
    """Return ``(edges, status)`` for SHARES_AUDIENCE edges (§5.2, C5).

    When ``05-graph.json`` is absent (``graph_doc is None``) this returns
    ``([], "deferred")`` so the loader records ``associations: deferred`` (A6).
    """
    if not graph_doc:
        return [], "deferred"

    edges: list[dict] = []
    for o in graph_doc.get("audience_overlap", []) or []:
        edges.append({
            "source_user_id": o.get("source_user_id") or o.get("a"),
            "target_user_id": o.get("target_user_id") or o.get("b"),
            "overlap_pct": o.get("overlap_pct"),
        })
    return edges, "loaded"
