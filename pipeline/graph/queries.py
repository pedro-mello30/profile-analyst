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


# ── Product-value queries (spec 0002 §1 use-cases) ────────────────────────────

_AQ5_CREATOR_PROFILE = """
MATCH (c:Creator {user_id: $user_id})
RETURN c.username AS username, c.followers_count AS followers_count,
       c.media_count AS media_count, c.verified AS verified
"""

_AQ6_MEDIA_COUNT = """
MATCH (c:Creator {user_id: $user_id})-[:HAS_MEDIA]->(m:Media)
RETURN count(m) AS n
"""

_AQ7_PRIMARY_NICHE = """
MATCH (c:Creator {user_id: $user_id})-[:HAS_SIGNAL]->(s:Signal {name: 'primary_niche', run_id: $run_id})
RETURN s.value AS niche
"""

_AQ8_RELATED_BY_NICHE = """
MATCH (c1:Creator {user_id: $user_id})-[:HAS_SIGNAL]->(s1:Signal {name: 'primary_niche', run_id: $run_id})
MATCH (c2:Creator)-[:HAS_SIGNAL]->(s2:Signal {name: 'primary_niche', run_id: $run_id})
WHERE c2.user_id <> c1.user_id AND s1.value = s2.value AND s1.value IS NOT NULL
RETURN c2.user_id AS user_id, c2.username AS username
ORDER BY c2.username
"""


def creator_profile(session, user_id: str) -> dict | None:
    """AQ5 — creator node properties (username, follower count, media count, verified)."""
    rows = session.read(_AQ5_CREATOR_PROFILE, user_id=user_id)
    return rows[0] if rows else None


def creator_media_count(session, user_id: str) -> int:
    """AQ6 — number of Media nodes connected to the creator via HAS_MEDIA."""
    rows = session.read(_AQ6_MEDIA_COUNT, user_id=user_id)
    return rows[0]["n"] if rows else 0


def primary_niche(session, user_id: str, run_id: str) -> str | None:
    """AQ7 — primary niche signal value for a creator in a given run."""
    rows = session.read(_AQ7_PRIMARY_NICHE, user_id=user_id, run_id=run_id)
    return rows[0]["niche"] if rows else None


def related_by_niche(session, user_id: str, run_id: str) -> list[dict]:
    """AQ8 — creators that share the same primary_niche signal value.

    Returns list of {user_id, username} dicts ordered by username.
    This is the graph traversal use-case: find similar creators via a shared
    signal node, answering questions flat JSON cannot.
    """
    return session.read(_AQ8_RELATED_BY_NICHE, user_id=user_id, run_id=run_id)


# ── GDS audit queries (spec 0004 §8) ──────────────────────────────────────────

_GQ1_FRAUD_RISK_CHAIN = """
MATCH (c:Creator)-[r:CONTRIBUTED_TO]->(s:Score {type: 'fraud_risk', run_id: $run_id})
MATCH (c)-[hs:HAS_SIGNAL]->(sig:Signal {source: 'gds', run_id: $run_id})
RETURN c.username AS username, s.value AS fraud_risk,
       collect({signal: sig.name, weight: hs.weight, value: sig.value,
                art9_risk: sig.art9_risk}) AS signals
ORDER BY fraud_risk DESC
LIMIT $limit
"""

_GQ2_ENGAGEMENT_PODS = """
MATCH (c:Creator)-[:HAS_SIGNAL]->(s:Signal {name: 'community_id', run_id: $run_id})
WITH s.value AS community, collect(c.username) AS members
WHERE size(members) > 1 AND size(members) <= $pod_max
RETURN community, members
ORDER BY size(members) DESC
"""

_GQ3_AUDIENCE_OVERLAP = """
MATCH (a:Creator)-[r:SHARES_AUDIENCE {run_id: $run_id}]->(b:Creator)
RETURN a.username AS source, b.username AS target, r.overlap_pct AS overlap_pct
ORDER BY r.overlap_pct DESC
"""


def fraud_risk_chain(session, run_id: str, *, limit: int = 20) -> list[dict]:
    """GQ1 — top fraud-risk creators with their contributing signal chain (Art. 22)."""
    return session.read(_GQ1_FRAUD_RISK_CHAIN, run_id=run_id, limit=limit)


def engagement_pods(session, run_id: str, *, pod_max: int = 8) -> list[dict]:
    """GQ2 — small, dense Louvain communities (engagement pods / fraud rings)."""
    return session.read(_GQ2_ENGAGEMENT_PODS, run_id=run_id, pod_max=pod_max)


def audience_overlap_gds(session, run_id: str) -> list[dict]:
    """GQ3 — SHARES_AUDIENCE edges written by Stage 9 (fills 0002 AQ2)."""
    return session.read(_GQ3_AUDIENCE_OVERLAP, run_id=run_id)
