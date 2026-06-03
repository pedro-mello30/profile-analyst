"""Tests for LinktreeAdapter — regression + new Spotify pattern."""
from unittest.mock import MagicMock, patch

import pytest

from pipeline.enrichment.adapter import AdapterConfig, AdapterContext
from pipeline.enrichment.adapters.linktree import LinktreeAdapter
from pipeline.enrichment.entity import make_entity

_NOW = "2026-06-03T00:00:00Z"


def _make_config() -> AdapterConfig:
    return AdapterConfig(
        profile_id="test-profile",
        run_id="test-run",
        max_depth=3,
        max_cost_usd=1.0,
        max_runtime_s=30,
        secrets={},
        osint_enabled=True,
        cache_enabled=False,
        dry_run=False,
        context=AdapterContext(raw_profile={}),
    )


def _bio_url_seed(url: str = "https://linktr.ee/testuser"):
    return [make_entity("bio_url", url, source="seed", confidence=1.0, depth=0, discovered_at=_NOW)]


def _mock_response(html: str):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Regression — YouTube handle still extracted
# ---------------------------------------------------------------------------

def test_youtube_handle_extracted():
    html = '<a href="https://youtube.com/@vida_com_ia">YouTube</a>'
    with patch("requests.get", return_value=_mock_response(html)):
        result = LinktreeAdapter().run(_bio_url_seed(), _make_config())
    types = {e.type for e in result.entities}
    assert "youtube_handle" in types
    values = [e.value for e in result.entities if e.type == "youtube_handle"]
    assert "@vida_com_ia" in values  # make_entity normalizes to @-prefixed form


# ---------------------------------------------------------------------------
# Bug fix — Spotify show URL → podcast_url entity
# ---------------------------------------------------------------------------

def test_spotify_show_url_produces_podcast_url():
    """open.spotify.com/show/... must produce a podcast_url entity (triggers SpotifyAdapter)."""
    html = '<a href="https://open.spotify.com/show/3yeqOp2pZKdqX5Qa3jY6Jz">Podcast</a>'
    with patch("requests.get", return_value=_mock_response(html)):
        result = LinktreeAdapter().run(_bio_url_seed(), _make_config())
    types = {e.type for e in result.entities}
    assert "podcast_url" in types, f"Expected podcast_url in {types}"
    values = [e.value for e in result.entities if e.type == "podcast_url"]
    assert any("3yeqOp2pZKdqX5Qa3jY6Jz" in v for v in values)


def test_spotify_episode_url_produces_podcast_url():
    html = '<a href="https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk">Episode</a>'
    with patch("requests.get", return_value=_mock_response(html)):
        result = LinktreeAdapter().run(_bio_url_seed(), _make_config())
    types = {e.type for e in result.entities}
    assert "podcast_url" in types


def test_spotify_show_appears_in_bio_link_platforms_signal():
    html = '<a href="https://open.spotify.com/show/3yeqOp2pZKdqX5Qa3jY6Jz">Podcast</a>'
    with patch("requests.get", return_value=_mock_response(html)):
        result = LinktreeAdapter().run(_bio_url_seed(), _make_config())
    platforms_signal = next(
        (s for s in result.signals if s.key == "bio_link_platforms"), None
    )
    assert platforms_signal is not None
    assert "podcast_url" in platforms_signal.value


# ---------------------------------------------------------------------------
# Dry run returns empty
# ---------------------------------------------------------------------------

def test_dry_run_returns_empty():
    cfg = AdapterConfig(
        profile_id="p", run_id="r", max_depth=2, max_cost_usd=1.0,
        max_runtime_s=10, secrets={}, osint_enabled=True, cache_enabled=False,
        dry_run=True, context=AdapterContext(raw_profile={}),
    )
    result = LinktreeAdapter().run(_bio_url_seed(), cfg)
    assert result.entities == []
    assert result.error is None
