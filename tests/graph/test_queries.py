"""Audit query tests — AQ1/AQ2/AQ3/AQ4."""
import json
import shutil
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


class TestAQ2AudienceOverlap:
    def test_empty_when_no_05_graph(self, project_dir, graph_session):
        """AQ2 returns [] when no 05-graph.json was loaded (v1 deferred state)."""
        run("sample_creator", project_dir, session=graph_session)
        uid = _creator_user_id()
        result = queries.audience_overlap(graph_session, uid)
        assert result == []

    def test_returns_overlap_edges_ordered_by_pct_desc(self, tmp_path, graph_session):
        """AQ2 returns SHARES_AUDIENCE edges sorted by overlap_pct descending."""
        for name in ("02-normalized.json", "03-features.json", "06-dossier.json"):
            shutil.copy(FIXTURE_ROOT / name, tmp_path / name)
        uid = _creator_user_id()
        graph_doc = {"audience_overlap": [
            {"source_user_id": uid, "target_user_id": "creator_b", "overlap_pct": 0.3},
            {"source_user_id": uid, "target_user_id": "creator_c", "overlap_pct": 0.7},
        ]}
        (tmp_path / "05-graph.json").write_text(json.dumps(graph_doc))
        run("sample_creator", tmp_path, session=graph_session)
        result = queries.audience_overlap(graph_session, uid)
        assert len(result) == 2
        assert result[0]["overlap_pct"] == 0.7
        assert result[1]["overlap_pct"] == 0.3


class TestAQ4UndisclosedSponsored:
    def test_empty_when_all_posts_disclosed(self, project_dir, graph_session):
        """AQ4 returns [] when likely_sponsored_undisclosed is empty (fixture default)."""
        run("sample_creator", project_dir, session=graph_session)
        uid = _creator_user_id()
        result = queries.undisclosed_sponsored(graph_session, uid)
        assert result == []

    def test_returns_undisclosed_media(self, tmp_path, graph_session):
        """AQ4 returns media_id + permalink for posts flagged as undisclosed."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
        shutil.copy(FIXTURE_ROOT / "06-dossier.json", tmp_path / "06-dossier.json")
        features = json.loads((FIXTURE_ROOT / "03-features.json").read_text())
        for feat in features["features"]:
            if feat["feature_id"] == "likely_sponsored_undisclosed":
                feat["value"] = ["m001"]
        (tmp_path / "03-features.json").write_text(json.dumps(features))
        run("sample_creator", tmp_path, session=graph_session)
        uid = _creator_user_id()
        result = queries.undisclosed_sponsored(graph_session, uid)
        assert len(result) == 1
        assert result[0]["media_id"] == "m001"
        assert "permalink" in result[0]
