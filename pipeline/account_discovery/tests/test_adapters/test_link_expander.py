"""Tests for LinkExpander adapter — uses stdlib mocking, no live HTTP."""
from unittest.mock import patch, MagicMock
from pipeline.account_discovery.adapters.link_expander import LinkExpander


def _entity(type_, value):
    class E: pass
    e = E(); e.type = type_; e.value = value; return e


def test_skips_non_hub_url():
    adapter = LinkExpander()
    seeds = [_entity("url", "https://youtube.com/channel/UC123")]
    assert adapter.run(seeds, None) == []


def test_returns_empty_on_http_failure():
    adapter = LinkExpander()
    with patch("pipeline.account_discovery.adapters.link_expander.urllib.request.urlopen",
               side_effect=Exception("connection refused")):
        seeds = [_entity("url", "https://linktr.ee/creator123")]
        result = adapter.run(seeds, None)
    assert result == []


def test_extracts_from_linktree_html():
    adapter = LinkExpander()
    fake_html = b'<a href="https://youtube.com/@Creator123">YouTube</a>'
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_html
    mock_resp.headers.get_content_charset.return_value = "utf-8"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("pipeline.account_discovery.adapters.link_expander.urllib.request.urlopen",
               return_value=mock_resp):
        seeds = [_entity("url", "https://linktr.ee/creator123")]
        accounts = adapter.run(seeds, None)
    assert any(a.platform == "youtube" for a in accounts)


def test_attribution_chain_non_empty():
    adapter = LinkExpander()
    fake_html = b'<a href="https://github.com/creator123">GitHub</a>'
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_html
    mock_resp.headers.get_content_charset.return_value = "utf-8"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("pipeline.account_discovery.adapters.link_expander.urllib.request.urlopen",
               return_value=mock_resp):
        seeds = [_entity("url", "https://linktr.ee/creator123")]
        accounts = adapter.run(seeds, None)
    for acc in accounts:
        assert len(acc.attribution_chain) > 0


def test_never_raises():
    adapter = LinkExpander()
    adapter.run([None, "bad", object()], None)  # must not raise
