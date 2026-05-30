"""Shared fixtures for graph tests — Neo4j availability detection + project setup.

DB-backed tests skip automatically when no Neo4j instance is reachable (spec 0002
Track F risk note: mappers/schema tests need no DB; loader/query tests do).
"""
import json
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest

from pipeline.graph import GraphSession, graph_config

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"


def neo4j_available() -> bool:
    cfg = graph_config()
    parsed = urlparse(cfg["uri"])
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture
def graph_session():
    if not neo4j_available():
        pytest.skip("no Neo4j instance reachable (set NEO4J_URI)")
    with GraphSession() as session:
        session.write("MATCH (n) DETACH DELETE n")
        try:
            yield session
        finally:
            session.write("MATCH (n) DETACH DELETE n")


@pytest.fixture
def project_dir(tmp_path):
    """A project dir seeded with the 02/03/06 fixtures (no 05 → associations deferred)."""
    for name in ("02-normalized.json", "03-features.json", "06-dossier.json"):
        shutil.copy(FIXTURE_ROOT / name, tmp_path / name)
    return tmp_path


def write_normalized(target_dir: Path, *, drop_governance: bool = False) -> None:
    doc = json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())
    if drop_governance:
        doc.pop("governance", None)
    (target_dir / "02-normalized.json").write_text(json.dumps(doc))
