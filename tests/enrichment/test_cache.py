import hashlib
import json
import pytest
from pathlib import Path
from pipeline.enrichment.cache import make_cache_key, read_cache, write_cache, is_expired, secure_delete


def test_cache_key_deterministic():
    assert make_cache_key("youtube", "youtube_channel_id", "UCxyz123") == \
           make_cache_key("youtube", "youtube_channel_id", "UCxyz123")

def test_cache_key_known_sha256():
    expected = hashlib.sha256(b"youtube:youtube_channel_id:UCxyz123").hexdigest()
    assert make_cache_key("youtube", "youtube_channel_id", "UCxyz123") == expected

def test_cache_key_differs_on_different_input():
    assert make_cache_key("youtube", "youtube_channel_id", "UCabc") != \
           make_cache_key("youtube", "youtube_channel_id", "UCxyz")

def test_write_and_read_cache(tmp_path):
    payload = {"signals_raw": [{"key": "sub_count", "value": 100}]}
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", payload, ttl_hours=24)
    result = read_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123")
    assert result is not None
    assert result["signals_raw"][0]["value"] == 100

def test_read_returns_none_on_miss(tmp_path):
    assert read_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is None

def test_is_not_expired_within_ttl(tmp_path):
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=24)
    assert is_expired(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is False

def test_is_expired_with_zero_ttl(tmp_path):
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=0)
    assert is_expired(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is True

def test_read_returns_none_when_expired(tmp_path):
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=0)
    assert read_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is None

def test_is_expired_on_missing_file(tmp_path):
    assert is_expired(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is True

def test_write_creates_cache_dir(tmp_path):
    nested = tmp_path / "a" / "b"
    write_cache(nested, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=1)
    assert nested.exists()

def test_secure_delete_file(tmp_path):
    f = tmp_path / "test.json"
    f.write_text("sensitive data")
    secure_delete(f)
    assert not f.exists()

def test_secure_delete_directory(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    (d / "a.json").write_text("data")
    (d / "b.json").write_text("more")
    secure_delete(d)
    assert not d.exists()

def test_secure_delete_nonexistent_is_noop(tmp_path):
    secure_delete(tmp_path / "does_not_exist.json")  # must not raise
