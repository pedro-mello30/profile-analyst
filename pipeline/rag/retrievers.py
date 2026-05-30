"""Three retriever adapters for Hybrid RAG (spec 0005 §6 / Track E).

All three return the same dict shape:
    {user_id: str, username: str, score: float, source: str}

* VectorRetriever   — semantic/paraphrase via ``db.index.vector.queryNodes``
* KeywordRetriever  — exact-term / BM25 via ``db.index.fulltext.queryNodes``
* GraphRetriever    — multi-hop relational via 0003 NL→Cypher (S1–S6 + read-only txn)

Creator identity is always via ``user_id`` (per 0002 §5.1). Traversals use
``HAS_MEDIA``, never ``POSTED``. 0004 GDS signals (fraud_risk, centrality,
community_id) are exposed in the graph-leg schema when present.
"""
from __future__ import annotations

import os
from typing import Any

_DEFAULT_K = 50


class VectorRetriever:
    """Retrieve creators/media semantically using the Neo4j native vector index.

    Runs ``db.index.vector.queryNodes`` over ``creator_embeddings`` (and
    optionally ``media_embeddings``, rolling up by max to the owning Creator).

    Args:
        session: A ``GraphSession`` (0002) in read mode.
    """

    def __init__(self, session) -> None:
        self._session = session

    def retrieve(
        self,
        embedding: list[float],
        k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to *k* creators ranked by vector similarity.

        Args:
            embedding: Query embedding vector (same dim as the index).
            k: Candidate cap. Defaults to ``RAG_VECTOR_K`` env var or 50.

        Returns:
            List of ``{user_id, username, score, source}`` dicts, best-first.
        """
        k = k or int(os.environ.get("RAG_VECTOR_K", _DEFAULT_K))

        # Creator-level vector search
        rows = self._session.read(
            """
            CALL db.index.vector.queryNodes('creator_embeddings', $k, $embedding)
            YIELD node AS c, score
            RETURN c.user_id  AS user_id,
                   c.username AS username,
                   score
            """,
            k=k,
            embedding=embedding,
        )
        seen: dict[str, dict] = {}
        for r in rows:
            uid = r.get("user_id", "")
            if not uid:
                continue
            if uid not in seen or r["score"] > seen[uid]["score"]:
                seen[uid] = {"user_id": uid, "username": r.get("username", ""), "score": r["score"]}

        # Media-level vector search — roll up to Creator by max score
        media_rows = self._session.read(
            """
            CALL db.index.vector.queryNodes('media_embeddings', $k, $embedding)
            YIELD node AS m, score
            MATCH (c:Creator)-[:HAS_MEDIA]->(m)
            RETURN c.user_id  AS user_id,
                   c.username AS username,
                   score
            """,
            k=k,
            embedding=embedding,
        )
        for r in media_rows:
            uid = r.get("user_id", "")
            if not uid:
                continue
            if uid not in seen or r["score"] > seen[uid]["score"]:
                seen[uid] = {"user_id": uid, "username": r.get("username", ""), "score": r["score"]}

        results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:k]
        for item in results:
            item["source"] = "vector"
        return results


class KeywordRetriever:
    """Retrieve creators/media by BM25 full-text search (exact-term / hashtag / handle).

    Runs ``db.index.fulltext.queryNodes`` over ``creator_fulltext`` and
    ``media_fulltext``. This mode recovers ``#ad``, ``@handles``, SKUs, and
    campaign hashtags that the vector mode blurs.

    Args:
        session: A ``GraphSession`` (0002) in read mode.
    """

    def __init__(self, session) -> None:
        self._session = session

    def retrieve(
        self,
        query: str,
        k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to *k* creators ranked by BM25 score.

        Args:
            query: The user's raw text query (tokens, hashtags, handles are matched literally).
            k: Candidate cap. Defaults to ``RAG_KEYWORD_K`` env var or 50.

        Returns:
            List of ``{user_id, username, score, source}`` dicts, best-first.
        """
        k = k or int(os.environ.get("RAG_KEYWORD_K", _DEFAULT_K))
        seen: dict[str, dict] = {}

        # Creator full-text
        rows = self._session.read(
            """
            CALL db.index.fulltext.queryNodes('creator_fulltext', $query, {limit: $k})
            YIELD node AS c, score
            RETURN c.user_id  AS user_id,
                   c.username AS username,
                   score
            """,
            query=query,
            k=k,
        )
        for r in rows:
            uid = r.get("user_id", "")
            if not uid:
                continue
            if uid not in seen or r["score"] > seen[uid]["score"]:
                seen[uid] = {"user_id": uid, "username": r.get("username", ""), "score": r["score"]}

        # Media full-text — roll up to Creator by max score
        media_rows = self._session.read(
            """
            CALL db.index.fulltext.queryNodes('media_fulltext', $query, {limit: $k})
            YIELD node AS m, score
            MATCH (c:Creator)-[:HAS_MEDIA]->(m)
            RETURN c.user_id  AS user_id,
                   c.username AS username,
                   score
            """,
            query=query,
            k=k,
        )
        for r in media_rows:
            uid = r.get("user_id", "")
            if not uid:
                continue
            if uid not in seen or r["score"] > seen[uid]["score"]:
                seen[uid] = {"user_id": uid, "username": r.get("username", ""), "score": r["score"]}

        results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:k]
        for item in results:
            item["source"] = "keyword"
        return results


class GraphRetriever:
    """Retrieve creators via the 0003 NL→Cypher path (multi-hop relational).

    Delegates entirely to ``tools/ask.py``'s NL→Cypher pipeline which enforces
    safety gates S1–S6 and runs queries in a read-only transaction.

    Creator identity is always via ``user_id``; traversal via ``HAS_MEDIA``
    (never ``POSTED``). When 0004 GDS signals are present in the graph
    (``Signal`` nodes with name ``community_id`` / ``centrality`` /
    ``fraud_risk``), the generated Cypher can access them for ranking.

    Args:
        handle: Optional creator handle to scope the graph query. When None,
                the whole graph is queried.
        k: Candidate cap. Defaults to ``RAG_GRAPH_K`` env var or 50.
    """

    def __init__(self, handle: str | None = None) -> None:
        self._handle = handle

    def retrieve(
        self,
        nl_query: str,
        k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Translate *nl_query* to Cypher via 0003 and return creators.

        Safety gates S1–S6 apply (write/admin denylist, read-only txn, schema
        grounding, resource bounds, parameterisation). See 0003 spec §6.

        Returns:
            List of ``{user_id, username, score, source}`` dicts.
            Score is positional (1/(rank+1)) since Cypher ORDER BY provides
            the rank, not a similarity score.
        """
        k = k or int(os.environ.get("RAG_GRAPH_K", _DEFAULT_K))

        from tools.ask import run_ask  # 0003 NL→Cypher entry point

        scope_hint = (
            f" Focus on creators matching handle '{self._handle}'."
            if self._handle
            else ""
        )
        scoped_query = (
            nl_query + scope_hint
            + f" Return up to {k} Creator nodes with their user_id and username."
            + " Always use HAS_MEDIA (never POSTED) when traversing to Media nodes."
        )

        try:
            result = run_ask(scoped_query, handle=self._handle)
        except Exception as exc:
            raise RuntimeError(f"GraphRetriever NL→Cypher failed: {exc}") from exc

        rows = result.get("rows", [])
        candidates: list[dict] = []
        for rank, row in enumerate(rows[:k], start=1):
            uid = row.get("user_id") or row.get("c.user_id", "")
            username = row.get("username") or row.get("c.username", "")
            if not uid:
                continue
            candidates.append({
                "user_id": uid,
                "username": username,
                "score": 1.0 / rank,
                "source": "graph",
            })
        return candidates
