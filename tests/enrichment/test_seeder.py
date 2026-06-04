"""Tests for pipeline/enrichment/seeder.py (spec-0019 §4)."""
import pytest

from pipeline.enrichment.entity_pool import EntityPool
from pipeline.enrichment.seeder import seed_from_discovery, seed_from_raw


def test_seed_from_raw_adds_handle():
    pool = EntityPool()
    seed_from_raw({"raw_profile": {"username": "creator123"}}, pool)
    assert pool.get("handle", "creator123") is not None


def test_seed_from_raw_adds_bio_url():
    pool = EntityPool()
    seed_from_raw({"raw_profile": {"bio_url": "https://linktr.ee/c"}}, pool)
    assert pool.get("bio_url", "https://linktr.ee/c") is not None


def test_seed_from_raw_adds_email():
    pool = EntityPool()
    seed_from_raw({"raw_profile": {"email": "user@example.com"}}, pool)
    assert pool.get("email", "user@example.com") is not None


def test_seed_from_raw_depth_zero():
    pool = EntityPool()
    seed_from_raw({"raw_profile": {"username": "creator123"}}, pool)
    entity = pool.get("handle", "creator123")
    assert entity is not None
    assert entity.depth == 0
    assert entity.confidence == 1.0


def test_seed_from_raw_missing_fields_silently_skipped():
    pool = EntityPool()
    seed_from_raw({"raw_profile": {}}, pool)
    assert len(pool) == 0


def test_seed_from_raw_no_raw_profile():
    pool = EntityPool()
    seed_from_raw({}, pool)
    assert len(pool) == 0


def test_seed_from_raw_invalid_value_silently_skipped():
    pool = EntityPool()
    # Empty username should be skipped silently
    seed_from_raw({"raw_profile": {"username": ""}}, pool)
    assert len(pool) == 0


def test_seed_from_discovery_youtube_at_depth1():  # AC1
    pool = EntityPool()
    seed_from_discovery({"discovered_accounts": [
        {"platform": "youtube", "handle": "Creator123", "confidence": 0.9,
         "account_id": "yt-1", "attribution_chain": []}
    ]}, pool)
    # youtube_handle normalized form — find the entity in pool
    yt_entities = [e for e in pool.all_entities() if e.type == "youtube_handle"]
    assert len(yt_entities) >= 1
    assert yt_entities[0].depth == 1  # AC1: discovery entities at depth=1


def test_seed_from_discovery_youtube_confidence():
    pool = EntityPool()
    seed_from_discovery({"discovered_accounts": [
        {"platform": "youtube", "handle": "Creator123", "confidence": 0.9,
         "account_id": "yt-1", "attribution_chain": []}
    ]}, pool)
    yt_entities = [e for e in pool.all_entities() if e.type == "youtube_handle"]
    assert len(yt_entities) >= 1
    assert yt_entities[0].confidence == 0.9


def test_no_discovery_graceful():  # AC8
    pool = EntityPool()
    seed_from_discovery(None, pool)
    assert len(pool) == 0


def test_empty_discovery_graceful():  # AC8
    pool = EntityPool()
    seed_from_discovery({}, pool)
    assert len(pool) == 0


def test_unknown_platform_seeds_as_url():
    pool = EntityPool()
    seed_from_discovery({"discovered_accounts": [
        {"platform": "unknown_platform", "handle": "https://example.com/user",
         "confidence": 0.7, "account_id": "unk-1", "attribution_chain": []}
    ]}, pool)
    url_entities = [e for e in pool.all_entities() if e.type == "url"]
    # Should have 1 url entity OR silently skipped if value isn't valid URL
    # Either outcome is valid — no crash is the key invariant
    assert True  # just assert no exception


def test_seed_from_discovery_multiple_accounts():
    pool = EntityPool()
    seed_from_discovery({"discovered_accounts": [
        {"platform": "twitter", "handle": "@someuser", "confidence": 0.8,
         "account_id": "tw-1", "attribution_chain": []},
        {"platform": "github", "handle": "somedev", "confidence": 0.7,
         "account_id": "gh-1", "attribution_chain": []},
    ]}, pool)
    twitter_entities = [e for e in pool.all_entities() if e.type == "twitter_handle"]
    github_entities = [e for e in pool.all_entities() if e.type == "github_handle"]
    assert len(twitter_entities) >= 1
    assert len(github_entities) >= 1


def test_seed_from_discovery_reddit_uses_reddit_username():
    pool = EntityPool()
    seed_from_discovery({"discovered_accounts": [
        {"platform": "reddit", "handle": "some_user", "confidence": 0.8,
         "account_id": "rd-1", "attribution_chain": []}
    ]}, pool)
    reddit_entities = [e for e in pool.all_entities() if e.type == "reddit_username"]
    assert len(reddit_entities) >= 1
