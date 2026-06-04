"""Tests for UrlResolver adapter."""
from unittest.mock import patch, MagicMock
from pipeline.account_discovery.adapters.url_resolver import UrlResolver


def _entity(type_, value):
    class E: pass
    e = E(); e.type = type_; e.value = value; return e


def test_returns_empty_when_no_redirect():
    adapter = UrlResolver()
    # url_resolver should return [] when final URL == original URL (no redirect)
    with patch.object(adapter, '_resolve_redirect', return_value=None):
        seeds = [_entity("url", "https://youtube.com/@creator")]
        result = adapter.run(seeds, None)
    assert result == []


def test_returns_empty_on_http_failure():
    adapter = UrlResolver()
    with patch.object(adapter, '_resolve_redirect', side_effect=Exception("fail")):
        seeds = [_entity("url", "https://bit.ly/abc")]
        result = adapter.run(seeds, None)
    assert result == []


def test_attribution_chain_includes_resolver():
    adapter = UrlResolver()
    with patch.object(adapter, '_resolve_redirect', return_value="https://github.com/creator"):
        seeds = [_entity("url", "https://bit.ly/abc")]
        accounts = adapter.run(seeds, None)
    for acc in accounts:
        assert any(s.adapter_id == "url_resolver" for s in acc.attribution_chain)


def test_never_raises():
    adapter = UrlResolver()
    adapter.run([None, "bad", object()], None)
