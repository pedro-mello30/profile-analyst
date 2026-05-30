"""Pure unit tests for gds_algorithms.py — no database, no driver (Track B / T9)."""
import pytest

from pipeline.graph.gds_algorithms import (
    parse_weights,
    normalize_minmax,
    community_sizes,
    pod_density,
    compute_fraud_scores,
    build_signal_rows,
    art9_communities_for,
    normalize_edge_probabilities,
)


class TestParseWeights:
    def test_parses_spec_string(self):
        w = parse_weights("pod:0.5,btw:0.3,deg:0.2")
        assert w == {"pod": 0.5, "btw": 0.3, "deg": 0.2}

    def test_none_returns_defaults(self):
        w = parse_weights(None)
        assert set(w.keys()) == {"pod", "btw", "deg"}
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_empty_string_returns_defaults(self):
        w = parse_weights("")
        assert "pod" in w

    def test_single_weight(self):
        w = parse_weights("pod:1.0")
        assert w["pod"] == 1.0


class TestNormalizeMinmax:
    def test_basic(self):
        n = normalize_minmax({"a": 0.0, "b": 5.0, "c": 10.0})
        assert n["a"] == pytest.approx(0.0)
        assert n["b"] == pytest.approx(0.5)
        assert n["c"] == pytest.approx(1.0)

    def test_all_equal(self):
        n = normalize_minmax({"x": 3.0, "y": 3.0})
        assert n["x"] == 0.0
        assert n["y"] == 0.0

    def test_empty(self):
        assert normalize_minmax({}) == {}

    def test_single(self):
        n = normalize_minmax({"a": 7.0})
        assert n["a"] == 0.0


class TestCommunitySizes:
    def test_counts(self):
        c = {"u1": 1, "u2": 1, "u3": 2, "u4": 2, "u5": 2}
        s = community_sizes(c)
        assert s[1] == 2
        assert s[2] == 3


class TestPodDensity:
    def test_pair_is_half(self):
        c = {"u1": 1, "u2": 1}
        pd = pod_density(c, pod_max=8)
        assert pd["u1"] == pytest.approx(0.5)
        assert pd["u2"] == pytest.approx(0.5)

    def test_singleton_is_zero(self):
        c = {"u1": 1}
        pd = pod_density(c, pod_max=8)
        assert pd["u1"] == 0.0

    def test_too_large_community_is_zero(self):
        c = {f"u{i}": 1 for i in range(10)}
        pd = pod_density(c, pod_max=8)
        for v in pd.values():
            assert v == 0.0


class TestComputeFraudScores:
    def test_output_keys_are_union_of_inputs(self):
        pod = {"u1": 0.5, "u2": 0.0}
        btw = {"u1": 0.8}
        deg = {"u1": 0.6, "u3": 1.0}
        w = {"pod": 0.5, "btw": 0.3, "deg": 0.2}
        scores = compute_fraud_scores(pod, btw, deg, w)
        assert set(scores.keys()) == {"u1", "u2", "u3"}

    def test_all_zero_inputs(self):
        scores = compute_fraud_scores({}, {}, {}, {"pod": 0.5, "btw": 0.3, "deg": 0.2})
        assert scores == {}

    def test_score_bounded_0_1(self):
        pod = {"u1": 1.0, "u2": 0.0}
        btw = {"u1": 1.0, "u2": 0.0}
        deg = {"u1": 1.0, "u2": 0.0}
        w = {"pod": 0.5, "btw": 0.3, "deg": 0.2}
        scores = compute_fraud_scores(pod, btw, deg, w)
        for v in scores.values():
            assert 0.0 <= v <= 1.0 + 1e-9

    def test_deterministic(self):
        pod = {"a": 0.5, "b": 0.3}
        btw = {"a": 0.7}
        deg = {"b": 0.9}
        w = {"pod": 0.4, "btw": 0.4, "deg": 0.2}
        assert compute_fraud_scores(pod, btw, deg, w) == compute_fraud_scores(pod, btw, deg, w)


class TestBuildSignalRows:
    def test_all_three_signals_emitted(self):
        c = {"u1": 1, "u2": 1}
        d = {"u1": 0.5, "u2": 0.3}
        b = {"u1": 0.1, "u2": 0.2}
        rows = build_signal_rows(c, d, b)
        names = [r["name"] for r in rows]
        assert "community_id" in names
        assert "degree_centrality" in names
        assert "betweenness_centrality" in names

    def test_method_and_source_via_cypher_not_here(self):
        # The build function sets art9_risk and confidence; method/source are set in Cypher.
        rows = build_signal_rows({"u1": 1}, {"u1": 0.5}, {"u1": 0.2})
        for r in rows:
            assert r["confidence"] == 1.0
            assert "art9_risk" in r

    def test_art9_community_flagged(self):
        c = {"u1": 99, "u2": 99, "u3": 7}
        rows = build_signal_rows(c, {}, {}, art9_communities={99})
        com_rows = [r for r in rows if r["name"] == "community_id"]
        flagged = {r["user_id"] for r in com_rows if r["art9_risk"]}
        assert "u1" in flagged
        assert "u2" in flagged
        assert "u3" not in flagged


class TestArt9CommunitiesFor:
    def test_finds_community_of_art9_user(self):
        communities = {"u1": 1, "u2": 1, "u3": 2}
        result = art9_communities_for(communities, ["u1"])
        assert 1 in result
        assert 2 not in result

    def test_empty_art9_users(self):
        assert art9_communities_for({"u1": 1}, []) == set()


class TestNormalizeEdgeProbabilities:
    def test_normalizes_to_0_1(self):
        edges = [{"a": "x", "b": "y", "probability": 2.0},
                 {"a": "x", "b": "z", "probability": 8.0}]
        out = normalize_edge_probabilities(edges)
        probs = [e["probability"] for e in out]
        assert min(probs) == pytest.approx(0.0)
        assert max(probs) == pytest.approx(1.0)

    def test_empty_returns_empty(self):
        assert normalize_edge_probabilities([]) == []

    def test_single_edge(self):
        out = normalize_edge_probabilities([{"a": "x", "b": "y", "probability": 5.0}])
        assert out[0]["probability"] == 0.0
