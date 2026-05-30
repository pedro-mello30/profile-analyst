"""Pure mapper unit tests — no database (spec 0002 Track C)."""
import json
from pathlib import Path

import pytest

from pipeline.graph.mappers import (
    creator_from_normalized,
    media_from_normalized,
    comments_from_media,
    users_from_comments,
    signals_from_features,
    scores_from_dossier,
    contributions,
    associations_from_graph,
    _safe_value,
)

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"
RUN_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def normalized():
    return json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())


@pytest.fixture
def features():
    return json.loads((FIXTURE_ROOT / "03-features.json").read_text())


@pytest.fixture
def dossier():
    return json.loads((FIXTURE_ROOT / "06-dossier.json").read_text())


class TestCreator:
    def test_user_id_from_profile_id(self, normalized):
        c = creator_from_normalized(normalized)
        assert c["user_id"] == normalized["profile_id"]
        assert c["username"] == normalized["handle"]

    def test_governance_props_present(self, normalized):
        c = creator_from_normalized(normalized)
        for field in ("gdpr_basis", "subject_jurisdiction", "tos_compliant_at_ingest", "source_id"):
            assert field in c
        assert c["gdpr_basis"] == "LEGITIMATE_INTERESTS"


class TestMedia:
    def test_all_media_mapped(self, normalized, features):
        rows = media_from_normalized(normalized, features)
        assert len(rows) == len(normalized["media"])

    def test_ftc_status_disclosed_for_sponsored(self, normalized, features):
        rows = {r["media_id"]: r for r in media_from_normalized(normalized, features)}
        # m003/m006 are paid partnerships and in sponsored_posts
        assert rows["m003"]["ftc_disclosure_status"] == "disclosed"
        assert rows["m012"]["ftc_disclosure_status"] == "disclosed"  # in sponsored_posts
        # m001 is organic
        assert rows["m001"]["ftc_disclosure_status"] == "none"

    def test_undisclosed_flagged(self, normalized):
        # Inject an undisclosed feature list to exercise the 'undisclosed' branch (AQ4/C4)
        features = {"features": [
            {"feature_id": "likely_sponsored_undisclosed", "value": ["m001"]},
        ]}
        rows = {r["media_id"]: r for r in media_from_normalized(normalized, features)}
        assert rows["m001"]["ftc_disclosure_status"] == "undisclosed"


class TestComments:
    def test_v1_int_counts_yield_no_comments(self, normalized):
        # SampleAdapter stores comment *counts*, not objects
        assert comments_from_media(normalized) == []

    def test_comment_objects_extracted(self):
        normalized = {"media": [{"media_id": "m1", "comments": [
            {"comment_id": "c1", "text": "hi", "author_username": "bob", "timestamp": "t"},
        ]}]}
        comments = comments_from_media(normalized)
        assert comments[0]["comment_id"] == "c1"
        assert comments[0]["media_id"] == "m1"
        users = users_from_comments(comments)
        assert users == [{"username": "bob", "is_bot_score": None}]


class TestSignals:
    def test_one_signal_per_feature(self, features):
        rows = signals_from_features(features, RUN_ID)
        assert len(rows) == len(features["features"])
        assert all(r["run_id"] == RUN_ID for r in rows)

    def test_art9_flag_preserved(self, features):
        rows = {r["name"]: r for r in signals_from_features(features, RUN_ID)}
        assert rows["primary_niche"]["art9_risk"] is True
        assert rows["er_by_followers"]["art9_risk"] is False

    def test_complex_value_json_encoded(self, features):
        rows = {r["name"]: r for r in signals_from_features(features, RUN_ID)}
        # brand_affinity_signals is a list of objects → JSON string
        val = rows["brand_affinity_signals"]["value"]
        assert isinstance(val, str)
        assert json.loads(val)[0]["brand"] == "FitGearPro" or "NutriBoost" in val

    def test_scalar_and_primitive_list_pass_through(self):
        assert _safe_value(6.34) == 6.34
        assert _safe_value(["a", "b"]) == ["a", "b"]
        assert isinstance(_safe_value([{"x": 1}]), str)


class TestScores:
    def test_scores_mapped_with_run_id(self, dossier):
        rows = scores_from_dossier(dossier, RUN_ID)
        types = {r["type"] for r in rows}
        assert "engagement_quality" in types
        assert all(r["run_id"] == RUN_ID and r["status"] == "active" for r in rows)

    def test_textual_signals_preserved(self, dossier):
        rows = {r["type"]: r for r in scores_from_dossier(dossier, RUN_ID)}
        assert len(rows["engagement_quality"]["signals"]) >= 1

    def test_contribution_weight_from_confidence(self, dossier):
        rows = scores_from_dossier(dossier, RUN_ID)
        contribs = {c["type"]: c["weight"] for c in contributions(rows)}
        by_type = {r["type"]: r for r in rows}
        assert contribs["engagement_quality"] == by_type["engagement_quality"]["confidence"]


class TestAssociations:
    def test_absent_graph_is_deferred(self):
        edges, status = associations_from_graph(None)
        assert edges == []
        assert status == "deferred"

    def test_present_graph_loaded(self):
        doc = {"audience_overlap": [
            {"source_user_id": "a", "target_user_id": "b", "overlap_pct": 0.3},
        ]}
        edges, status = associations_from_graph(doc)
        assert status == "loaded"
        assert edges[0]["overlap_pct"] == 0.3
