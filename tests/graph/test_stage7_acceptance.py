"""Spec-0002 acceptance tests — product-value validation.

These tests verify that the graph answers the questions the product is designed to
answer, not merely that nodes are stored.  They go beyond the spec criteria (A1-A8)
to validate the four graph use-cases listed in spec-0002 §1:

  1. Creator data actually lands in the graph (persistence)
  2. Media edges are structurally correct (relationship integrity)
  3. Running the pipeline twice never creates duplicates (idempotency)
  4. Niche signal is queryable after the full pipeline (user journey)
  5. Two creators that share a niche are discoverable via graph traversal (acceptance)

Test 5 is the key product-value test: Neo4j's value is not "storing data" but
"answering questions that flat JSON cannot".
"""
import json
import shutil
from pathlib import Path

import pytest

from pipeline.stage7_load import run
from pipeline.graph import queries
from tests.graph.conftest import FIXTURE_ROOT


def _creator_user_id() -> str:
    return json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())["profile_id"]


def _setup_creator(
    target_dir: Path,
    *,
    uid: str,
    username: str,
    primary_niche: str,
) -> None:
    """Seed a project directory with a custom creator derived from the base fixture."""
    norm = json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())
    norm["profile_id"] = uid
    norm["handle"] = username
    (target_dir / "02-normalized.json").write_text(json.dumps(norm))

    feats = json.loads((FIXTURE_ROOT / "03-features.json").read_text())
    for f in feats["features"]:
        if f["feature_id"] == "primary_niche":
            f["value"] = primary_niche
    (target_dir / "03-features.json").write_text(json.dumps(feats))

    shutil.copy(FIXTURE_ROOT / "06-dossier.json", target_dir / "06-dossier.json")


# ── 1. Persistence — the object really lands in Neo4j ────────────────────────

class TestPersistence:
    def test_creator_node_has_correct_username(self, project_dir, graph_session):
        """After load, the Creator node carries the handle from 02-normalized.json."""
        run("sample_creator", project_dir, session=graph_session)
        uid = _creator_user_id()
        result = queries.creator_profile(graph_session, uid)
        assert result is not None
        assert result["username"] == "sample_creator"
        assert result["followers_count"] == 45_000


# ── 2. Relationship integrity — the graph structure is correct ────────────────

class TestRelationshipIntegrity:
    def test_creator_has_expected_media_count_via_edges(self, project_dir, graph_session):
        """HAS_MEDIA edges exist and match the media count in the manifest."""
        run("sample_creator", project_dir, session=graph_session)
        uid = _creator_user_id()
        assert queries.creator_media_count(graph_session, uid) == 12

    def test_signal_edges_carry_weight(self, project_dir, graph_session):
        """HAS_SIGNAL edges have weight == confidence of the signal (spec §5.2)."""
        run("sample_creator", project_dir, session=graph_session, run_id="r1")
        uid = _creator_user_id()
        result = queries.explain_score(graph_session, uid, "engagement_quality", "r1")
        for sig in result["signals"]:
            assert sig["weight"] is not None
            assert sig["weight"] == sig["confidence"]


# ── 3. Idempotency — running twice never creates duplicates ───────────────────

class TestIdempotency:
    def test_creator_count_stays_one_after_two_loads(self, project_dir, graph_session):
        """Re-loading the same creator does not create a second Creator node."""
        run("sample_creator", project_dir, session=graph_session)
        run("sample_creator", project_dir, session=graph_session)
        rows = graph_session.read("MATCH (c:Creator) RETURN count(c) AS n")
        assert rows[0]["n"] == 1

    def test_media_count_stable_after_two_loads(self, project_dir, graph_session):
        """Re-loading does not duplicate Media nodes."""
        run("sample_creator", project_dir, session=graph_session)
        run("sample_creator", project_dir, session=graph_session)
        assert queries.creator_media_count(graph_session, _creator_user_id()) == 12


# ── 4. User journey — full pipeline → queryable niche signal ─────────────────

class TestUserJourney:
    def test_primary_niche_queryable_after_pipeline(self, project_dir, graph_session):
        """After Stage 7, the creator's primary niche is retrievable from the graph."""
        run("sample_creator", project_dir, session=graph_session, run_id="r1")
        uid = _creator_user_id()
        niche = queries.primary_niche(graph_session, uid, "r1")
        assert niche == "Fitness/Health"

    def test_engagement_score_queryable_after_pipeline(self, project_dir, graph_session):
        """After Stage 7, the engagement_quality score is retrievable with its signal chain."""
        run("sample_creator", project_dir, session=graph_session, run_id="r1")
        uid = _creator_user_id()
        result = queries.explain_score(graph_session, uid, "engagement_quality", "r1")
        assert result is not None
        assert result["value"] is not None


# ── 5. Acceptance — the graph answers questions flat JSON cannot ───────────────

class TestAcceptance:
    def test_related_creators_discoverable_by_shared_niche(self, tmp_path, graph_session):
        """Two creators with the same primary_niche are linked via graph traversal.

        This is the core product-value test: Neo4j's value is answering 'who else is
        in the same niche?' — a question that requires graph traversal, not a filter.
        """
        dir_a = tmp_path / "creator_a"
        dir_b = tmp_path / "creator_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _setup_creator(dir_a, uid="uid_a", username="fitness_a", primary_niche="Fitness/Health")
        _setup_creator(dir_b, uid="uid_b", username="fitness_b", primary_niche="Fitness/Health")

        run("fitness_a", dir_a, session=graph_session, run_id="rid")
        run("fitness_b", dir_b, session=graph_session, run_id="rid")

        related = queries.related_by_niche(graph_session, "uid_a", "rid")
        user_ids = {r["user_id"] for r in related}
        assert "uid_b" in user_ids

    def test_different_niche_creators_not_related(self, tmp_path, graph_session):
        """Creators in different niches are not returned as related."""
        dir_a = tmp_path / "creator_a"
        dir_b = tmp_path / "creator_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _setup_creator(dir_a, uid="uid_a", username="fitness_a", primary_niche="Fitness/Health")
        _setup_creator(dir_b, uid="uid_b", username="tech_b",    primary_niche="Tech/Gaming")

        run("fitness_a", dir_a, session=graph_session, run_id="rid")
        run("tech_b",    dir_b, session=graph_session, run_id="rid")

        related = queries.related_by_niche(graph_session, "uid_a", "rid")
        user_ids = {r["user_id"] for r in related}
        assert "uid_b" not in user_ids
