"""Neo4j vector + full-text index management for Hybrid RAG (spec 0005 §10.1 / Track B).

``ensure_rag_indexes`` is idempotent — safe to call on every Stage 8 run.
It uses ``IF NOT EXISTS`` so it never raises on an already-existing index.

Neo4j 5.13+ is required (vector index GA); the function verifies this up front
and raises ``Neo4jVersionError`` with a clear message if the requirement is not met.
"""
from __future__ import annotations

NEO4J_MIN_VERSION = (5, 13)
_DEFAULT_SIMILARITY = "cosine"


class Neo4jVersionError(RuntimeError):
    """Raised when the connected Neo4j instance is older than 5.13."""


class DimensionMismatchError(RuntimeError):
    """Raised when EMBED_DIMENSIONS ≠ the model's probed output dimension."""


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z(-enterprise)' → (X, Y, Z)."""
    base = version_str.split("-")[0]
    try:
        return tuple(int(p) for p in base.split("."))
    except ValueError:
        return (0,)


def check_neo4j_version(session) -> None:
    """Verify Neo4j ≥ 5.13; raise Neo4jVersionError otherwise."""
    rows = session.read("CALL dbms.components() YIELD versions RETURN versions[0] AS v")
    if not rows:
        raise Neo4jVersionError("Could not determine Neo4j version via dbms.components().")
    version_str = rows[0]["v"]
    version = _parse_version(version_str)
    if version < NEO4J_MIN_VERSION:
        raise Neo4jVersionError(
            f"Neo4j {'.'.join(map(str, NEO4J_MIN_VERSION))}+ is required for vector indexes "
            f"(spec 0005 §10.1). Connected instance reports version {version_str}. "
            "Upgrade to Neo4j 5.13+ (Community edition is sufficient)."
        )


def ensure_rag_indexes(
    session,
    dimensions: int,
    similarity: str = _DEFAULT_SIMILARITY,
    probed_dimension: int | None = None,
) -> None:
    """Create (or confirm) the four RAG indexes on the 0002 graph.

    Raises:
        Neo4jVersionError: if Neo4j < 5.13.
        DimensionMismatchError: if *probed_dimension* is given and differs from *dimensions*.
    """
    if probed_dimension is not None and probed_dimension != dimensions:
        raise DimensionMismatchError(
            f"EMBED_DIMENSIONS={dimensions} does not match the embedding model's "
            f"actual output dimension ({probed_dimension}). "
            "Update EMBED_DIMENSIONS or rebuild the indexes with the correct dimension. "
            "To rebuild: drop the existing vector indexes and re-run --stage 8."
        )

    check_neo4j_version(session)

    # Vector indexes — require Neo4j 5.13+ (vector index GA)
    session.run(
        f"""
        CREATE VECTOR INDEX creator_embeddings IF NOT EXISTS
        FOR (c:Creator) ON (c.embedding)
        OPTIONS {{
            indexConfig: {{
                `vector.dimensions`: {dimensions},
                `vector.similarity_function`: '{similarity}'
            }}
        }}
        """
    )
    session.run(
        f"""
        CREATE VECTOR INDEX media_embeddings IF NOT EXISTS
        FOR (m:Media) ON (m.embedding)
        OPTIONS {{
            indexConfig: {{
                `vector.dimensions`: {dimensions},
                `vector.similarity_function`: '{similarity}'
            }}
        }}
        """
    )

    # Full-text indexes (Lucene/BM25) — for keyword/exact-term retrieval
    session.run(
        """
        CREATE FULLTEXT INDEX creator_fulltext IF NOT EXISTS
        FOR (c:Creator) ON EACH [c.username, c.display_name, c.bio]
        """
    )
    session.run(
        """
        CREATE FULLTEXT INDEX media_fulltext IF NOT EXISTS
        FOR (m:Media) ON EACH [m.caption_text]
        """
    )
