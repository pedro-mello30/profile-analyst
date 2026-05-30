"""Neo4j connection plumbing — a thin GraphSession wrapper over the official driver.

Spec 0002 §9. The neo4j driver is imported lazily so this module (and the mappers
that import from the package) load cleanly even when the driver is not installed.
"""
from __future__ import annotations

import os
from typing import Any


def graph_config() -> dict[str, str]:
    """Resolve Neo4j connection config from the environment (spec §9)."""
    return {
        "uri": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        "user": os.environ.get("NEO4J_USER", "neo4j"),
        "password": os.environ.get("NEO4J_PASSWORD", ""),
        "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
    }


def _collect(tx, cypher: str, params: dict) -> list[dict]:
    """Transaction function: run cypher and materialize records inside the tx."""
    return [record.data() for record in tx.run(cypher, **params)]


class GraphSession:
    """Context manager around a Neo4j driver + session.

    Provides ``write`` / ``read`` helpers (managed transactions) and ``run``
    (auto-commit, used for schema commands which cannot share a data transaction).
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        cfg = graph_config()
        self.uri = uri or cfg["uri"]
        self.user = user or cfg["user"]
        self.password = password if password is not None else cfg["password"]
        self.database = database or cfg["database"]
        self._driver = None
        self._session = None

    def __enter__(self) -> "GraphSession":
        from neo4j import GraphDatabase  # lazy import — driver optional at module load

        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._session = self._driver.session(database=self.database)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            self._session.close()
        if self._driver is not None:
            self._driver.close()
        self._session = None
        self._driver = None

    def write(self, cypher: str, **params: Any) -> list[dict]:
        """Run *cypher* in a managed write transaction; returns record dicts."""
        return self._session.execute_write(_collect, cypher, params)

    def read(self, cypher: str, **params: Any) -> list[dict]:
        """Run *cypher* in a managed read transaction; returns record dicts."""
        return self._session.execute_read(_collect, cypher, params)

    def run(self, cypher: str, **params: Any) -> None:
        """Auto-commit a statement (schema commands: CREATE CONSTRAINT/INDEX)."""
        self._session.run(cypher, **params).consume()
