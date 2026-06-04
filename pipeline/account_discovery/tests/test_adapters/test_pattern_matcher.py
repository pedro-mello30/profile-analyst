"""Tests for PatternMatcher adapter."""
from pipeline.account_discovery.adapters.pattern_matcher import PatternMatcher


def _entity(type_, value):
    class E: pass
    e = E(); e.type = type_; e.value = value; return e


def test_matches_github_url():
    adapter = PatternMatcher()
    seeds = [_entity("url", "https://github.com/creator-dev")]
    accounts = adapter.run(seeds, None)
    assert any(a.platform == "github" and a.handle == "creator-dev" for a in accounts)


def test_matches_youtube_url():
    adapter = PatternMatcher()
    seeds = [_entity("url", "https://youtube.com/@Creator123")]
    accounts = adapter.run(seeds, None)
    assert any(a.platform == "youtube" for a in accounts)


def test_returns_empty_for_unknown_url():
    adapter = PatternMatcher()
    seeds = [_entity("url", "https://example.com/nothing")]
    assert adapter.run(seeds, None) == []


def test_attribution_chain_non_empty():
    adapter = PatternMatcher()
    seeds = [_entity("url", "https://tiktok.com/@creator")]
    accounts = adapter.run(seeds, None)
    for acc in accounts:
        assert len(acc.attribution_chain) > 0


def test_never_raises():
    adapter = PatternMatcher()
    adapter.run([None, "bad", object()], None)
