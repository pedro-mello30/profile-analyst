"""Neo4j GDS plugin gate + in-memory projection lifecycle (spec 0004 §6).

Stage 9 runs over a native in-memory projection of the co-engagement graph: two
Creators are linked, weighted by how many distinct commenters (Users) they share.
The projection is dropped before and after every run (``A9`` projection hygiene).

Requires the Neo4j GDS plugin (Cypher aggregation projection ⇒ GDS 2.4+).
"""
from __future__ import annotations


class GdsUnavailableError(RuntimeError):
    """Raised when the GDS plugin is not installed / ``gds.version()`` is unavailable."""


# Co-engagement projection (governance-gated). Two Creators are connected with a
# ``weight`` equal to the count of distinct commenters they share. Built directly
# in memory via the GDS Cypher aggregation projection — no edges written to the store.
_PROJECT_CO_ENGAGEMENT = """
MATCH (a:Creator)-[:HAS_MEDIA]->(:Media)-[:HAS_COMMENT]->(:Comment)-[:FROM_USER]->(u:User)
MATCH (b:Creator)-[:HAS_MEDIA]->(:Media)-[:HAS_COMMENT]->(:Comment)-[:FROM_USER]->(u)
WHERE elementId(a) < elementId(b){gov}
WITH a, b, count(DISTINCT u) AS shared
WHERE shared > 0
RETURN gds.graph.project(
  $graph_name, a, b,
  {{ relationshipProperties: {{ weight: shared }} }},
  {{ undirectedRelationshipTypes: ['*'] }}
) AS g
"""

# Governance predicate (C1) — both endpoints must carry complete governance metadata.
_GOV_PREDICATE = (
    " AND a.gdpr_basis IS NOT NULL AND a.subject_jurisdiction IS NOT NULL "
    "AND a.tos_compliant_at_ingest IS NOT NULL "
    "AND b.gdpr_basis IS NOT NULL AND b.subject_jurisdiction IS NOT NULL "
    "AND b.tos_compliant_at_ingest IS NOT NULL"
)


def gds_version(session) -> str | None:
    """Return the installed GDS version, or ``None`` when the plugin is absent."""
    try:
        rows = session.read("RETURN gds.version() AS version")
    except Exception:
        return None
    return rows[0]["version"] if rows else None


def assert_gds_available(session) -> str:
    """Return the GDS version or raise :class:`GdsUnavailableError` (A8)."""
    version = gds_version(session)
    if not version:
        raise GdsUnavailableError(
            "Neo4j GDS plugin not installed (gds.version() unavailable). "
            "Install the GDS plugin (>=2.4) to run Stage 9."
        )
    return version


def drop_projection(session, graph_name: str) -> None:
    """Drop the named in-memory projection if it exists (idempotent; failOnMissing=false)."""
    session.write("CALL gds.graph.drop($graph_name, false) YIELD graphName", graph_name=graph_name)


def project_co_engagement(session, graph_name: str, *, gate_governance: bool = True) -> dict:
    """Build the co-engagement projection. Returns the projection summary row.

    When *gate_governance* is true (default, C1) only Creators with complete
    governance metadata are projected.
    """
    cypher = _PROJECT_CO_ENGAGEMENT.format(gov=_GOV_PREDICATE if gate_governance else "")
    rows = session.write(cypher, graph_name=graph_name)
    return rows[0]["g"] if rows else {}
