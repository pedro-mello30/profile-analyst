"""Unit tests for RRFFusion (Track F, T23) — pure, no DB."""
from __future__ import annotations

import pytest

from pipeline.rag.fusion import RRFFusion


def _make_candidates(ids_scores: list[tuple[str, float]], source: str) -> list[dict]:
    return [
        {"user_id": uid, "username": f"user_{uid}", "score": score, "source": source}
        for uid, score in ids_scores
    ]


class TestRRFOrder:
    def test_single_mode_preserves_order(self):
        fusion = RRFFusion(rrf_k=60, top_k=10)
        mode_results = {
            "vector": _make_candidates([("a", 0.9), ("b", 0.7), ("c", 0.5)], "vector"),
        }
        fused = fusion.fuse(mode_results)
        ids = [r["user_id"] for r in fused]
        assert ids == ["a", "b", "c"]

    def test_consensus_candidate_ranked_higher(self):
        """A creator ranked #1 in vector and #1 in keyword should beat one that only
        appears in one mode."""
        fusion = RRFFusion(rrf_k=60, top_k=10)
        mode_results = {
            "vector":  _make_candidates([("shared", 0.9), ("vector_only", 0.8)], "vector"),
            "keyword": _make_candidates([("shared", 0.9), ("keyword_only", 0.8)], "keyword"),
        }
        fused = fusion.fuse(mode_results)
        ids = [r["user_id"] for r in fused]
        assert ids[0] == "shared"

    def test_three_modes_fused_correctly(self):
        fusion = RRFFusion(rrf_k=60, top_k=5)
        # "alpha" appears in all three modes at rank 1 → should win
        mode_results = {
            "vector":  _make_candidates([("alpha", 1.0), ("beta", 0.5)], "vector"),
            "keyword": _make_candidates([("alpha", 1.0), ("gamma", 0.5)], "keyword"),
            "graph":   _make_candidates([("alpha", 1.0), ("delta", 0.5)], "graph"),
        }
        fused = fusion.fuse(mode_results)
        assert fused[0]["user_id"] == "alpha"

    def test_deterministic_on_same_input(self):
        fusion = RRFFusion(rrf_k=60, top_k=5)
        mode_results = {
            "vector":  _make_candidates([("a", 0.9), ("b", 0.7)], "vector"),
            "keyword": _make_candidates([("b", 0.8), ("c", 0.6)], "keyword"),
        }
        result1 = fusion.fuse(mode_results)
        result2 = fusion.fuse(mode_results)
        assert [r["user_id"] for r in result1] == [r["user_id"] for r in result2]


class TestWeightOverride:
    def test_higher_weight_mode_dominates(self):
        """When vector weight is 10x, a vector-only candidate should rank above
        a keyword-only candidate at the same rank."""
        fusion = RRFFusion(rrf_k=60, weights={"vector": 10.0, "keyword": 1.0}, top_k=5)
        mode_results = {
            "vector":  _make_candidates([("vec_creator", 0.9)], "vector"),
            "keyword": _make_candidates([("kw_creator", 0.9)], "keyword"),
        }
        fused = fusion.fuse(mode_results)
        assert fused[0]["user_id"] == "vec_creator"

    def test_weights_recorded_in_manifest(self):
        weights = {"vector": 2.0, "keyword": 0.5}
        fusion = RRFFusion(weights=weights)
        manifest = fusion.fusion_manifest({}, [])
        assert manifest["weights"] == weights
        assert manifest["method"] == "RRF"
        assert manifest["rrf_k"] == fusion.rrf_k


class TestTopKTruncation:
    def test_truncates_to_top_k(self):
        fusion = RRFFusion(top_k=2)
        mode_results = {
            "vector": _make_candidates(
                [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6)], "vector"
            ),
        }
        fused = fusion.fuse(mode_results)
        assert len(fused) <= 2


class TestMediaRollup:
    def test_media_level_candidates_roll_up_to_creator(self):
        """Items without user_id should be silently skipped (rolled-up upstream)."""
        fusion = RRFFusion(top_k=5)
        mode_results = {
            "vector": [
                {"user_id": "creator_1", "username": "c1", "score": 0.9, "source": "vector"},
                # item missing user_id — should be ignored
                {"user_id": "", "username": "", "score": 0.8, "source": "vector"},
            ]
        }
        fused = fusion.fuse(mode_results)
        assert all(r["user_id"] for r in fused)
        assert len(fused) == 1


class TestSources:
    def test_sources_list_contains_contributing_modes(self):
        fusion = RRFFusion(top_k=5)
        mode_results = {
            "vector":  _make_candidates([("alice", 0.9)], "vector"),
            "keyword": _make_candidates([("alice", 0.8)], "keyword"),
        }
        fused = fusion.fuse(mode_results)
        alice = next(r for r in fused if r["user_id"] == "alice")
        assert "vector" in alice["sources"]
        assert "keyword" in alice["sources"]
