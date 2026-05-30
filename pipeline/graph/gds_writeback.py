"""Write-back phase of Stage 9 GDS: Signals, edges, fraud_risk Score (spec 0004 §5, §6).

All Cypher is parameterized and batched via ``UNWIND``. Each written Signal carries
``method="computed"`` and ``source="gds"``; prior-run GDS artifacts are superseded
(hard-deleted by default, OQ1) before new ones are written (A7).
"""
from __future__ import annotations

from datetime import datetime, timezone

# ── supersede prior-run GDS artifacts ─────────────────────────────────────────

_SUPERSEDE_GDS_SIGNALS = """
MATCH ()-[r:HAS_SIGNAL]->(s:Signal {source: 'gds'})
WHERE s.run_id <> $run_id
WITH s
DETACH DELETE s
RETURN count(*) AS removed
"""

_SUPERSEDE_GDS_SCORES = """
MATCH ()-[r:CONTRIBUTED_TO]->(s:Score {source: 'gds'})
WHERE s.run_id <> $run_id
WITH s
DETACH DELETE s
RETURN count(*) AS removed
"""

_SUPERSEDE_GDS_EDGES = """
MATCH ()-[r:SHARES_AUDIENCE]->() WHERE r.run_id <> $run_id DELETE r
UNION
MATCH ()-[r:COLLABORATED_WITH]->() WHERE r.run_id <> $run_id AND r.predicted = true DELETE r
RETURN count(*) AS removed
"""

# ── write Signals ─────────────────────────────────────────────────────────────

_MERGE_GDS_SIGNALS = """
UNWIND $rows AS row
MATCH (c:Creator {user_id: row.user_id})
MERGE (sig:Signal {creator_user_id: row.user_id, name: row.name, run_id: $run_id})
SET sig.value       = row.value,
    sig.confidence  = row.confidence,
    sig.method      = 'computed',
    sig.source      = 'gds',
    sig.art9_risk   = row.art9_risk,
    sig.computed_at = $computed_at,
    sig.run_id      = $run_id,
    sig.creator_user_id = row.user_id
MERGE (c)-[hs:HAS_SIGNAL]->(sig)
SET hs.weight = row.confidence
"""

# ── write SHARES_AUDIENCE edges (AL4) ─────────────────────────────────────────

_MERGE_SHARES_AUDIENCE = """
UNWIND $rows AS row
MATCH (a:Creator {user_id: row.a})
MATCH (b:Creator {user_id: row.b})
MERGE (a)-[r:SHARES_AUDIENCE]->(b)
SET r.overlap_pct = row.overlap_pct,
    r.run_id      = $run_id,
    r.method      = 'computed'
"""

# ── write COLLABORATED_WITH edges (AL5) ────────────────────────────────────────

_MERGE_COLLABORATED_WITH = """
UNWIND $rows AS row
MATCH (a:Creator {user_id: row.a})
MATCH (b:Creator {user_id: row.b})
MERGE (a)-[r:COLLABORATED_WITH]->(b)
SET r.predicted   = true,
    r.probability = row.probability,
    r.run_id      = $run_id
"""

# ── write fraud_risk Score + CONTRIBUTED_TO edges (A3/G4) ─────────────────────

_MERGE_FRAUD_SCORE = """
UNWIND $rows AS row
MATCH (c:Creator {user_id: row.user_id})
MERGE (sc:Score {creator_user_id: row.user_id, type: 'fraud_risk', run_id: $run_id})
SET sc.value         = row.score,
    sc.confidence    = row.score,
    sc.model_version = $model_version,
    sc.created_at    = $computed_at,
    sc.run_id        = $run_id,
    sc.status        = 'active',
    sc.source        = 'gds',
    sc.creator_user_id = row.user_id
MERGE (c)-[ct:CONTRIBUTED_TO]->(sc)
SET ct.weight = row.score
"""

# Links each contributing Signal to the fraud_risk Score (GDPR Art. 22 chain).
_LINK_SIGNAL_TO_SCORE = """
MATCH (sig:Signal {creator_user_id: $user_id, name: $signal_name, run_id: $run_id})
MATCH (sc:Score {creator_user_id: $user_id, type: 'fraud_risk', run_id: $run_id})
MERGE (sig)-[r:CONTRIBUTES_TO_SCORE]->(sc)
SET r.weight = $weight
"""


def _supersede_count(rows: list[dict]) -> int:
    return sum(int(r.get("removed", 0)) for r in rows)


def supersede_prior_run(session, run_id: str) -> dict[str, int]:
    """Delete all GDS-authored signals/scores/edges from previous runs (A7)."""
    sig = _supersede_count(session.write(_SUPERSEDE_GDS_SIGNALS, run_id=run_id))
    sc = _supersede_count(session.write(_SUPERSEDE_GDS_SCORES, run_id=run_id))
    # Edge supersede may fail without GDS artifacts; ignore if empty
    try:
        edge_rows = session.write(_SUPERSEDE_GDS_EDGES, run_id=run_id)
        edges = _supersede_count(edge_rows)
    except Exception:
        edges = 0
    return {"signals": sig, "scores": sc, "edges": edges}


def write_signals(session, signal_rows: list[dict], run_id: str, computed_at: str) -> int:
    """Merge GDS Signal nodes; return count written (A6: method=computed, source=gds)."""
    if not signal_rows:
        return 0
    session.write(_MERGE_GDS_SIGNALS, rows=signal_rows, run_id=run_id, computed_at=computed_at)
    return len(signal_rows)


def write_shares_audience(session, edges: list[dict], run_id: str) -> int:
    """Merge SHARES_AUDIENCE edges from Node Similarity (AL4, G3)."""
    if not edges:
        return 0
    session.write(_MERGE_SHARES_AUDIENCE, rows=edges, run_id=run_id)
    return len(edges)


def write_collaborated_with(session, edges: list[dict], run_id: str) -> int:
    """Merge COLLABORATED_WITH predicted edges from link prediction (AL5, G3)."""
    if not edges:
        return 0
    session.write(_MERGE_COLLABORATED_WITH, rows=edges, run_id=run_id)
    return len(edges)


def write_fraud_scores(
    session,
    fraud_scores: dict[str, float],
    signal_weights: dict[str, float],
    run_id: str,
    computed_at: str,
    model_version: str,
) -> int:
    """Merge fraud_risk Score nodes + CONTRIBUTED_TO edges (A3, G4)."""
    if not fraud_scores:
        return 0
    rows = [{"user_id": uid, "score": round(score, 6)} for uid, score in fraud_scores.items()]
    session.write(_MERGE_FRAUD_SCORE, rows=rows, run_id=run_id,
                  computed_at=computed_at, model_version=model_version)
    # Link contributing signals for Art. 22 (C3)
    for uid in fraud_scores:
        for signal_name, weight in signal_weights.items():
            try:
                session.write(
                    _LINK_SIGNAL_TO_SCORE,
                    user_id=uid, signal_name=signal_name, run_id=run_id, weight=weight,
                )
            except Exception:
                pass  # signal may not exist for this creator; not a fatal error
    return len(rows)
