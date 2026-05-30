"""Audit query tests — AQ1 (A3) + AQ3 (A4). Skip when no Neo4j is reachable."""
import json
from pathlib import Path

from pipeline.stage7_load import run
from pipeline.graph import queries
from tests.graph.conftest import FIXTURE_ROOT


def _creator_user_id() -> str:
    return json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())["profile_id"]


class TestAuditQueries:
    def test_a3_explain_score_full_signal_chain(self, project_dir, graph_session):
        """AQ1: each signal entry carries weight, value, source, confidence, method."""
        run("sample_creator", project_dir, session=graph_session, run_id="rid-1")
        uid = _creator_user_id()
        result = queries.explain_score(graph_session, uid, "engagement_quality", "rid-1")
        assert result is not None
        assert result["type"] == "engagement_quality"
        assert len(result["signals"]) >= 1
        for entry in result["signals"]:
            for key in ("signal", "weight", "value", "source", "confidence", "method", "art9_risk"):
                assert key in entry

    def test_a4_art9_signals_returned(self, project_dir, graph_session):
        """AQ3: Signals flagged art9_risk in features are flagged in Neo4j and returned."""
        run("sample_creator", project_dir, session=graph_session, run_id="rid-1")
        uid = _creator_user_id()
        rows = queries.art9_signals(graph_session, uid, "rid-1")
        names = {r["name"] for r in rows}
        # primary_niche + caption_sentiment are art9_risk:true in the fixture
        assert "primary_niche" in names
