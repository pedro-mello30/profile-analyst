"""Audit / read queries over the creator graph (spec 0002 §8).

Parameterized helpers returning plain dicts. Each takes an open ``GraphSession``.
"""
from __future__ import annotations

_AQ1_EXPLAIN_SCORE = """
MATCH (c:Creator {user_id: $user_id})-[r:CONTRIBUTED_TO]->(s:Score {type: $score_type})
WHERE s.run_id = $run_id
MATCH (c)-[hs:HAS_SIGNAL]->(sig:Signal {run_id: $run_id})
RETURN c.username AS username, s.type AS type, s.value AS value,
       s.model_version AS model_version,
       collect({signal: sig.name, weight: hs.weight, value: sig.value,
                source: sig.source, confidence: sig.confidence,
                method: sig.method, art9_risk: sig.art9_risk}) AS signals
"""

_AQ2_AUDIENCE_OVERLAP = """
MATCH (a:Creator {user_id: $user_id})-[r:SHARES_AUDIENCE]->(b:Creator)
RETURN a.username AS source, b.username AS target, r.overlap_pct AS overlap_pct
ORDER BY r.overlap_pct DESC
"""

_AQ3_ART9_SIGNALS = """
MATCH (c:Creator {user_id: $user_id})-[:HAS_SIGNAL]->(s:Signal {art9_risk: true})
WHERE s.run_id = $run_id
RETURN c.username AS username, s.name AS name, s.value AS value,
       s.method AS method, s.confidence AS confidence
"""

_AQ4_UNDISCLOSED = """
MATCH (c:Creator {user_id: $user_id})-[:HAS_MEDIA]->(m:Media)
WHERE m.ftc_disclosure_status = 'undisclosed'
RETURN c.username AS username, m.media_id AS media_id,
       m.permalink AS permalink, m.timestamp AS timestamp
"""


def explain_score(session, user_id: str, score_type: str, run_id: str) -> dict | None:
    """AQ1 — GDPR Art. 22 score explanation: the full signal chain for one score."""
    rows = session.read(_AQ1_EXPLAIN_SCORE, user_id=user_id, score_type=score_type, run_id=run_id)
    return rows[0] if rows else None


def audience_overlap(session, user_id: str) -> list[dict]:
    """AQ2 — duplicate-reach / audience overlap (empty until [v2])."""
    return session.read(_AQ2_AUDIENCE_OVERLAP, user_id=user_id)


def art9_signals(session, user_id: str, run_id: str) -> list[dict]:
    """AQ3 — Art. 9 special-category inferences for a creator."""
    return session.read(_AQ3_ART9_SIGNALS, user_id=user_id, run_id=run_id)


def undisclosed_sponsored(session, user_id: str) -> list[dict]:
    """AQ4 — undisclosed sponsored posts (FTC)."""
    return session.read(_AQ4_UNDISCLOSED, user_id=user_id)
