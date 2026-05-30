"""NL→Cypher orchestration tests — generation→validation→execution→manifest (A1,A2,A5,A7,A9).

The Ollama daemon and (for orchestration tests) Neo4j are faked, so these run in CI without
services. The read-only enforcement test (A3) needs a live Neo4j and skips when none is reachable.
"""
import json

import pytest

import tools.ask as ask_mod
from tools.ask import ReadOnlyGraph, ask
from tests.graph.conftest import neo4j_available

SCHEMA_LABELS = ["Creator", "Media", "Signal"]
SCHEMA_RELS = ["HAS_MEDIA", "HAS_SIGNAL"]
SCHEMA_PROPS = ["user_id", "username", "media_id", "ftc_disclosure_status", "name", "value",
                "art9_risk", "method", "confidence"]


class FakeGraph:
    """In-memory stand-in for ReadOnlyGraph (no DB)."""

    def __init__(self, rows, uri="bolt://fake:7687", database="neo4j"):
        self.uri = uri
        self.database = database
        self._rows = rows

    def labels(self):
        return list(SCHEMA_LABELS)

    def relationship_types(self):
        return list(SCHEMA_RELS)

    def property_keys(self):
        return list(SCHEMA_PROPS)

    def run_read(self, cypher, params, timeout_ms, max_rows):
        return self._rows[:max_rows]


class FakeOllama:
    """Returns a canned Cypher JSON for generation calls (fmt='json') and a canned answer otherwise."""

    host = "http://localhost:11434"

    def __init__(self, cypher_obj, answer="Here is the grounded answer."):
        self._cypher_json = json.dumps(cypher_obj)
        self._answer = answer
        self.calls = []

    def chat(self, model, messages, *, options=None, fmt=None):
        self.calls.append(fmt)
        if fmt == "json":
            return self._cypher_json
        return self._answer


@pytest.fixture(autouse=True)
def _clear_schema_cache():
    ask_mod._SCHEMA_CACHE.clear()
    yield
    ask_mod._SCHEMA_CACHE.clear()


# ── A1 — happy path: grounded answer + schema-valid manifest ────────────────────

def test_a1_grounded_answer_and_valid_manifest(tmp_path):
    graph = FakeGraph(rows=[{"media_id": "m1"}, {"media_id": "m2"}])
    ollama = FakeOllama({
        "cypher": "MATCH (c:Creator {user_id:$uid})-[:HAS_MEDIA]->(m:Media) "
                  "WHERE m.ftc_disclosure_status='undisclosed' RETURN m.media_id AS media_id",
        "params": {"uid": "sample_creator"},
        "rationale": "undisclosed media",
    }, answer="Two undisclosed posts: m1, m2.")

    res = ask("sample_creator", "list undisclosed sponsored posts",
              graph=graph, ollama=ollama, projects_root=tmp_path)

    assert res.exit_code == 0
    assert res.manifest["validation"]["passed"] is True
    assert res.manifest["row_count"] == 2
    assert res.manifest["data_egress"] == "local-only"   # A7
    assert res.manifest["read_only"] is True
    assert res.manifest["model_role"] == "cypher"
    assert res.manifest_path.exists()
    # manifest persisted under projects/<handle>/queries/
    assert res.manifest_path.parent == tmp_path / "sample_creator" / "queries"
    # LIMIT auto-injected (S5)
    assert "LIMIT" in res.manifest["cypher"]


# ── A2 — mutation question rejected pre-execution ───────────────────────────────

def test_a2_mutation_rejected_and_recorded(tmp_path):
    graph = FakeGraph(rows=[])
    ollama = FakeOllama({
        "cypher": "MATCH (c:Creator) DETACH DELETE c",
        "params": {},
        "rationale": "delete users",
    })

    res = ask("sample_creator", "delete all bot users",
              graph=graph, ollama=ollama, projects_root=tmp_path)

    assert res.exit_code != 0
    assert res.manifest["validation"]["passed"] is False
    codes = [r["reason_code"] for r in res.manifest["validation"]["reasons"]]
    assert "WRITE_KEYWORD" in codes
    assert res.manifest["row_count"] == 0
    assert res.manifest_path.exists()  # manifest written even on rejection


# ── A4 — unknown property rejected ──────────────────────────────────────────────

def test_a4_unknown_property_rejected(tmp_path):
    graph = FakeGraph(rows=[])
    ollama = FakeOllama({
        "cypher": "MATCH (c:Creator) RETURN c.political_affiliation",
        "params": {},
        "rationale": "hallucinated field",
    })
    res = ask("sample_creator", "what is their political affiliation",
              graph=graph, ollama=ollama, projects_root=tmp_path)
    assert res.exit_code != 0
    codes = [r["reason_code"] for r in res.manifest["validation"]["reasons"]]
    assert "UNKNOWN_PROPERTY" in codes


# ── A5 — zero-row answer asserts no facts ───────────────────────────────────────

def test_a5_zero_rows_grounding(tmp_path):
    graph = FakeGraph(rows=[])
    ollama = FakeOllama({
        "cypher": "MATCH (c:Creator {user_id:$uid})-[:HAS_MEDIA]->(m:Media) RETURN m.media_id AS media_id",
        "params": {"uid": "nobody"},
        "rationale": "none",
    }, answer="The graph returned no matching data.")
    res = ask("nobody", "list their posts", graph=graph, ollama=ollama, projects_root=tmp_path)
    assert res.exit_code == 0
    assert res.manifest["row_count"] == 0


# ── A9 — Art. 9 notice surfaced ─────────────────────────────────────────────────

def test_a9_art9_notice_surfaced(tmp_path):
    graph = FakeGraph(rows=[{"name": "health_inference", "art9_risk": True, "value": "fitness"}])
    ollama = FakeOllama({
        "cypher": "MATCH (c:Creator {user_id:$uid})-[:HAS_SIGNAL]->(s:Signal {art9_risk:true}) "
                  "RETURN s.name AS name, s.art9_risk AS art9_risk, s.value AS value",
        "params": {"uid": "sample_creator"},
        "rationale": "art9 signals",
    }, answer="There is one sensitive signal.")  # model omits the notice on purpose
    res = ask("sample_creator", "what sensitive inferences exist",
              graph=graph, ollama=ollama, projects_root=tmp_path)
    assert res.exit_code == 0
    assert "art. 9" in res.manifest["answer"].lower()


# ── A3 — read-only transaction enforcement (needs live Neo4j) ───────────────────

@pytest.mark.skipif(not neo4j_available(), reason="no Neo4j instance reachable (set NEO4J_URI)")
def test_a3_write_fails_in_read_session():
    """Even if validation were bypassed, a write fails because the session is read-only."""
    with ReadOnlyGraph() as g:
        with pytest.raises(Exception):
            g.run_read("CREATE (x:_AskProbe {id: 1}) RETURN x", {}, timeout_ms=5000, max_rows=10)
