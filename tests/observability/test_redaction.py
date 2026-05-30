"""Tests for Art. 9 redaction in span payloads (A7).

Verifies that raw special-category content is never written into trace payloads
by the redact_art9() hook in observability/spans.py.
"""
import pytest
from observability.spans import redact_art9


# Synthetic Art. 9 fixture — content that MUST be redacted
_ART9_FIXTURE = {
    "bio": "I struggle with chronic depression and anxiety",
    "caption": "Proud to be part of the LGBTQ+ community #pride",
    "caption_sentiment": "positive",
    "primary_niche": "Health and Mental Wellness",
    "user_id": "user_123",          # must NOT be redacted
    "followers_count": 50000,        # must NOT be redacted
    "username": "creator_handle",    # must NOT be redacted
    "signals": [
        {
            "name": "engagement_rate",
            "value": 0.042,
            "bio": "shares health journey",  # nested Art.9 field
        }
    ],
}


def test_art9_fields_are_redacted():
    """Known Art. 9 fields are replaced with a hashed placeholder."""
    result = redact_art9(_ART9_FIXTURE)

    # Art.9-risk string fields must not contain raw text
    assert "depression" not in result["bio"]
    assert "LGBTQ" not in result["caption"]
    assert "positive" not in result["caption_sentiment"]
    assert "Mental" not in result["primary_niche"]

    # Placeholders follow the expected format
    for field in ["bio", "caption", "caption_sentiment", "primary_niche"]:
        assert result[field].startswith("<redacted:art9:")


def test_non_art9_fields_pass_through():
    """Non-Art.9 fields are returned unchanged."""
    result = redact_art9(_ART9_FIXTURE)
    assert result["user_id"] == "user_123"
    assert result["followers_count"] == 50000
    assert result["username"] == "creator_handle"


def test_nested_dict_redaction():
    """Redaction applies recursively to nested dicts."""
    result = redact_art9(_ART9_FIXTURE)
    nested = result["signals"][0]
    assert "shares health" not in nested["bio"]
    assert nested["bio"].startswith("<redacted:art9:")


def test_list_passthrough_for_non_strings():
    """Numeric values in lists are not affected."""
    payload = {"scores": [0.1, 0.9, 0.5], "bio": "fitness journey"}
    result = redact_art9(payload)
    assert result["scores"] == [0.1, 0.9, 0.5]
    assert result["bio"].startswith("<redacted:art9:")


def test_redact_empty_payload():
    assert redact_art9({}) == {}
    assert redact_art9([]) == []
    assert redact_art9(None) is None


def test_redact_is_deterministic():
    """Same input produces the same redacted output."""
    payload = {"bio": "my bio content"}
    r1 = redact_art9(payload)
    r2 = redact_art9(payload)
    assert r1["bio"] == r2["bio"]


def test_no_raw_art9_in_trace_payload():
    """End-to-end: a payload carrying Art. 9 text has no raw content after redaction (A7)."""
    raw_payload = {
        "inputs": {
            "bio": "openly gay fitness creator",
            "caption": "celebrating Ramadan this week #faith",
        },
        "outputs": {
            "answer": "Creator has strong engagement",
            "primary_niche": "Religious Lifestyle",
        },
    }
    redacted = redact_art9(raw_payload)

    # Check that none of the Art.9 strings survive in any nested level
    payload_str = str(redacted)
    assert "gay" not in payload_str
    assert "Ramadan" not in payload_str
    assert "Religious Lifestyle" not in payload_str
    assert "<redacted:art9:" in payload_str
