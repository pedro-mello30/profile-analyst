"""Stage 9 GDS tests — compliance gate (A5/A8, DB-free) + integration (skips without Neo4j+GDS)."""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.graph.gds import GdsUnavailableError
from tests.graph.conftest import neo4j_available


# ── A8: plugin gate (no DB) ────────────────────────────────────────────────────

class TestGdsPluginGate:
    def test_gds_unavailable_raises(self, tmp_path, monkeypatch):
        """A8: absent plugin raises GdsUnavailableError before any DB write."""
        monkeypatch.setenv("ALLOW_NONCOMPLIANT", "false")
        from pipeline.graph.gds import GdsUnavailableError

        # Patch assert_gds_available to simulate missing plugin
        with patch("pipeline.stage9_gds.assert_gds_available",
                   side_effect=GdsUnavailableError("GDS not installed")):
            with patch("pipeline.stage9_gds.GraphSession") as MockSession:
                mock_sess = MagicMock()
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False

                from pipeline.stage9_gds import run
                with pytest.raises(GdsUnavailableError, match="GDS not installed"):
                    run("sample_creator", tmp_path)

                # No write calls should have happened
                mock_sess.write.assert_not_called()


# ── Pure unit: parse_weights, compute_fraud_scores, build_signal_rows ────────────
# (covered in test_gds_algorithms.py; this file focuses on the stage orchestration)


# ── Compliance gate (A5, no DB) ───────────────────────────────────────────────

class TestComplianceGate:
    def test_noncompliant_flag_propagates(self, tmp_path, monkeypatch):
        """allow_noncompliant_flag=True results in gate_gov=False passed to projection."""
        monkeypatch.delenv("ALLOW_NONCOMPLIANT", raising=False)
        calls = {}

        def fake_assert_gds(sess):
            return "2.6.0"

        def fake_drop(sess, name):
            pass

        def fake_project(sess, name, *, gate_governance=True):
            calls["gate_governance"] = gate_governance
            return {}

        with (
            patch("pipeline.stage9_gds.assert_gds_available", side_effect=fake_assert_gds),
            patch("pipeline.stage9_gds.drop_projection", side_effect=fake_drop),
            patch("pipeline.stage9_gds.project_co_engagement", side_effect=fake_project),
            patch("pipeline.stage9_gds.wb.supersede_prior_run", return_value={"signals": 0, "scores": 0, "edges": 0}),
            patch("pipeline.stage9_gds.algo.run_louvain", return_value={}),
            patch("pipeline.stage9_gds.algo.run_degree", return_value={}),
            patch("pipeline.stage9_gds.algo.run_betweenness", return_value={}),
            patch("pipeline.stage9_gds.algo.run_node_similarity", return_value=[]),
            patch("pipeline.stage9_gds.algo.run_link_prediction", return_value=[]),
            patch("pipeline.stage9_gds.algo.build_signal_rows", return_value=[]),
            patch("pipeline.stage9_gds.algo.compute_fraud_scores", return_value={}),
            patch("pipeline.stage9_gds.wb.write_signals", return_value=0),
            patch("pipeline.stage9_gds.wb.write_shares_audience", return_value=0),
            patch("pipeline.stage9_gds.wb.write_collaborated_with", return_value=0),
            patch("pipeline.stage9_gds.wb.write_fraud_scores", return_value=0),
            patch("pipeline.stage9_gds.GraphSession") as MockSession,
            patch("pipeline.stage9_gds._art9_user_ids", return_value=[]),
        ):
            mock_sess = MagicMock()
            MockSession.return_value.__enter__.return_value = mock_sess
            MockSession.return_value.__exit__.return_value = False

            from pipeline.stage9_gds import run
            out = run("sample_creator", tmp_path, allow_noncompliant_flag=True)

        assert calls.get("gate_governance") is False
        assert out.exists()


# ── Integration: real Neo4j + GDS (skips when unavailable) ─────────────────────

@pytest.fixture
def gds_session():
    """Skip when Neo4j is unreachable (no GDS check here; stage asserts internally)."""
    if not neo4j_available():
        pytest.skip("no Neo4j instance reachable (set NEO4J_URI)")
    from pipeline.graph import GraphSession
    with GraphSession() as session:
        session.write("MATCH (n) DETACH DELETE n")
        try:
            yield session
        finally:
            session.write("MATCH (n) DETACH DELETE n")


class TestStage9Integration:
    def test_a1_manifest_valid(self, tmp_path, gds_session):
        import jsonschema
        from pipeline.stage9_gds import run
        out = run("sample_creator", tmp_path, session=gds_session)
        data = json.loads(out.read_text())
        schema = json.loads((Path(__file__).parent.parent.parent / "schemas" / "11-gds.schema.json").read_text())
        jsonschema.validate(data, schema)

    def test_a9_projection_dropped_after_run(self, tmp_path, gds_session):
        from pipeline.stage9_gds import run
        graph_name = os.environ.get("GDS_GRAPH_NAME", "profile-analyst")
        run("sample_creator", tmp_path, session=gds_session)
        rows = gds_session.read(
            "CALL gds.graph.exists($g) YIELD exists RETURN exists",
            g=graph_name,
        )
        assert not rows[0]["exists"]

    def test_a10_validate_schema(self, tmp_path, gds_session):
        import subprocess, sys
        from pipeline.stage9_gds import run
        run("sample_creator", tmp_path, session=gds_session)
        result = subprocess.run(
            [sys.executable, "tools/validate.py"], capture_output=True, text=True
        )
        assert result.returncode == 0
