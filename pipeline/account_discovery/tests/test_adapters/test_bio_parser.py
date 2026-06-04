"""Tests for pipeline.account_discovery.adapters.bio_parser (spec-0018 §5)."""
from __future__ import annotations

import pytest

from pipeline.account_discovery.adapters.bio_parser import BioParsing
from pipeline.governance import validate_discovery_adapter_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(etype: str, value: str):
    """Return a plain dict seed entity."""
    return {"type": etype, "value": value}


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_passes_governance_contract():
    """BioParsing must pass validate_discovery_adapter_contract without error."""
    adapter = BioParsing()
    validate_discovery_adapter_contract(adapter)  # raises AdapterContractError on failure


# ---------------------------------------------------------------------------
# Core extraction tests
# ---------------------------------------------------------------------------


def test_extracts_youtube_from_bio():
    adapter = BioParsing()
    bio = "Check my channel at https://youtube.com/@Creator123 for videos!"
    entities = [_make_entity("bio_text", bio)]
    accounts = adapter.run(entities, None)
    youtube_accounts = [a for a in accounts if a.platform == "youtube"]
    assert youtube_accounts, "Expected at least one YouTube account"
    handles = [a.handle for a in youtube_accounts]
    assert any("Creator123" in h for h in handles), f"Creator123 not found in handles: {handles}"


def test_extracts_github_from_bio():
    adapter = BioParsing()
    bio = "My open-source work: https://github.com/myuser"
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    github = [a for a in accounts if a.platform == "github"]
    assert github
    assert "myuser" in github[0].handle


def test_extracts_tiktok_from_bio():
    adapter = BioParsing()
    bio = "Follow me on TikTok: https://tiktok.com/@dancequeen99"
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    tiktok = [a for a in accounts if a.platform == "tiktok"]
    assert tiktok
    assert "dancequeen99" in tiktok[0].handle


def test_extracts_twitter_from_bio():
    adapter = BioParsing()
    bio = "Tweets at https://twitter.com/news_anchor"
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    twitter = [a for a in accounts if a.platform == "twitter"]
    assert twitter
    assert "news_anchor" in twitter[0].handle


def test_extracts_twitch_from_bio():
    adapter = BioParsing()
    bio = "Live at https://twitch.tv/streamerguy"
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    twitch = [a for a in accounts if a.platform == "twitch"]
    assert twitch
    assert "streamerguy" in twitch[0].handle


def test_extracts_multiple_platforms_from_bio():
    adapter = BioParsing()
    bio = (
        "YouTube: https://youtube.com/@vlogmaster "
        "GitHub: https://github.com/vlogmaster "
        "TikTok: https://tiktok.com/@vlogmaster"
    )
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    platforms = {a.platform for a in accounts}
    assert {"youtube", "github", "tiktok"}.issubset(platforms)


# ---------------------------------------------------------------------------
# Edge cases / robustness
# ---------------------------------------------------------------------------


def test_returns_empty_for_no_bio():
    adapter = BioParsing()
    assert adapter.run([], None) == []


def test_returns_empty_for_bio_with_no_urls():
    adapter = BioParsing()
    bio = "Just a regular bio with no social links."
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    assert accounts == []


def test_ignores_non_bio_text_entities():
    adapter = BioParsing()
    entities = [
        _make_entity("url", "https://youtube.com/@ignored"),
        _make_entity("platform_handle", "ignored"),
    ]
    assert adapter.run(entities, None) == []


def test_handles_object_entities_with_attrs():
    """Accepts seed entities that expose .type / .value attributes (not dicts)."""
    class FakeEntity:
        type = "bio_text"
        value = "See https://github.com/objuser for code"

    adapter = BioParsing()
    accounts = adapter.run([FakeEntity()], None)
    github = [a for a in accounts if a.platform == "github"]
    assert github
    assert "objuser" in github[0].handle


# ---------------------------------------------------------------------------
# AC2 — attribution_chain invariant
# ---------------------------------------------------------------------------


def test_attribution_chain_non_empty():
    """Every returned DiscoveredAccount must have a non-empty attribution_chain (AC2)."""
    adapter = BioParsing()
    bio = "https://github.com/creator"
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    assert accounts, "Expected at least one account"
    for account in accounts:
        assert account.attribution_chain, (
            f"attribution_chain must be non-empty for account {account.account_id}"
        )


def test_attribution_chain_references_adapter():
    """attribution_chain steps must reference the bio_parser adapter_id."""
    adapter = BioParsing()
    bio = "https://github.com/creator"
    accounts = adapter.run([_make_entity("bio_text", bio)], None)
    for account in accounts:
        adapter_ids = {step.adapter_id for step in account.attribution_chain}
        assert "bio_parser" in adapter_ids, (
            f"Expected 'bio_parser' in attribution adapter_ids, got {adapter_ids}"
        )


# ---------------------------------------------------------------------------
# Safety — never raises
# ---------------------------------------------------------------------------


def test_never_raises_on_bad_input():
    """run() must not raise even when given garbage inputs."""
    adapter = BioParsing()
    adapter.run([None, "bad", 42, {"type": None, "value": None}], None)  # no exception


def test_never_raises_on_none_config():
    adapter = BioParsing()
    adapter.run([_make_entity("bio_text", "https://github.com/x")], None)


def test_never_raises_with_none_entity_list():
    """Passing None directly should not raise (graceful degradation)."""
    adapter = BioParsing()
    # This exercises the outer try/except
    try:
        result = adapter.run(None, None)  # type: ignore[arg-type]
        assert result == []
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"run() raised unexpectedly: {exc}")
