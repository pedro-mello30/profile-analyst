"""Unit tests for PlatformPresenceExtractor (spec 0015 Track B)."""
from __future__ import annotations

import pytest

from pipeline.enrichment.platform_presence import (
    PlatformPresenceBlock,
    PlatformPresenceExtractor,
    PlatformRow,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sig(key: str, value, *, confidence: float = 1.0, source: str = "test",
         osint_risk: bool = False, method: str = "api") -> dict:
    return {
        "key": key,
        "value": value,
        "unit": None,
        "confidence": confidence,
        "method": method,
        "source": source,
        "osint_risk": osint_risk,
    }


def _map(*signals: dict) -> dict:
    return {"signals": list(signals)}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHappyPath:
    """Test 1 — YouTube + podcast signals produce two rows."""

    def test_two_platforms_found(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, source="youtube"),
            _sig("youtube_video_count", 61, source="youtube"),
            _sig("podcast_episode_count", 38, source="itunes"),
        )
        block = PlatformPresenceExtractor.extract(em)

        assert isinstance(block, PlatformPresenceBlock)
        assert set(block.platforms_found) == {"youtube", "podcast"}
        assert block.uplift_advisory is True
        assert len(block.rows) == 2

    def test_youtube_key_metric(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, source="youtube"),
            _sig("youtube_video_count", 61, source="youtube"),
        )
        block = PlatformPresenceExtractor.extract(em)
        yt_row = next(r for r in block.rows if r.platform == "youtube")
        assert yt_row.key_metric == "4,200 subscribers · 61 videos"

    def test_podcast_key_metric(self):
        em = _map(_sig("podcast_episode_count", 38, source="itunes"))
        block = PlatformPresenceExtractor.extract(em)
        pod_row = next(r for r in block.rows if r.platform == "podcast")
        assert pod_row.key_metric == "38 episodes"

    def test_row_confidence_is_max(self):
        em = _map(_sig("youtube_subscriber_count", 4200, confidence=0.9, source="youtube"))
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows[0].confidence == 0.9

    def test_row_sources_sorted(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, source="youtube"),
            _sig("youtube_video_count", 61, source="youtube"),
        )
        block = PlatformPresenceExtractor.extract(em)
        yt_row = next(r for r in block.rows if r.platform == "youtube")
        assert yt_row.sources == ["youtube"]


class TestNoneInput:
    """Test 2 — None input returns empty block."""

    def test_none_returns_empty_block(self):
        block = PlatformPresenceExtractor.extract(None)
        assert block.platforms_found == []
        assert block.uplift_advisory is False
        assert block.rows == []
        assert block.narrative == ""


class TestConfidenceFloor:
    """Test 3 — Signal below min_confidence is excluded."""

    def test_low_confidence_excluded_by_default(self):
        em = _map(_sig("youtube_subscriber_count", 1000, confidence=0.5))
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows == []
        assert block.uplift_advisory is False

    def test_signal_at_floor_included(self):
        em = _map(_sig("youtube_subscriber_count", 1000, confidence=0.7))
        block = PlatformPresenceExtractor.extract(em)
        assert len(block.rows) == 1

    def test_custom_floor_excludes(self):
        em = _map(_sig("youtube_subscriber_count", 1000, confidence=0.8))
        block = PlatformPresenceExtractor.extract(em, min_confidence=0.9)
        assert block.rows == []

    def test_custom_floor_includes(self):
        em = _map(_sig("youtube_subscriber_count", 1000, confidence=0.8))
        block = PlatformPresenceExtractor.extract(em, min_confidence=0.8)
        assert len(block.rows) == 1


class TestOsintRisk:
    """Test 4 — osint_risk signals excluded by default; included when expose_osint=True."""

    def test_osint_excluded_by_default(self):
        em = _map(_sig("github_followers", 500, osint_risk=True, source="maigret"))
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows == []

    def test_osint_included_when_flag_set(self):
        em = _map(_sig("github_followers", 500, osint_risk=True, source="maigret"))
        block = PlatformPresenceExtractor.extract(em, expose_osint=True)
        assert len(block.rows) == 1
        assert block.rows[0].platform == "github"

    def test_non_osint_signal_always_included(self):
        em = _map(_sig("github_followers", 500, osint_risk=False, source="github"))
        block = PlatformPresenceExtractor.extract(em)
        assert len(block.rows) == 1


class TestDeduplication:
    """Test 5 — Same signal key from two sources → one row, sources sorted, confidence = max."""

    def test_single_row_for_duplicate_sources(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, confidence=0.9, source="youtube"),
            _sig("youtube_subscriber_count", 4200, confidence=0.95, source="maigret"),
        )
        block = PlatformPresenceExtractor.extract(em)
        assert len(block.rows) == 1

    def test_sources_sorted(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, confidence=0.9, source="youtube"),
            _sig("youtube_subscriber_count", 4200, confidence=0.95, source="maigret"),
        )
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows[0].sources == ["maigret", "youtube"]

    def test_confidence_is_max(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, confidence=0.9, source="youtube"),
            _sig("youtube_subscriber_count", 4200, confidence=0.95, source="maigret"),
        )
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows[0].confidence == 0.95


class TestZeroQualifyingSignals:
    """Test 6 — enrichment_map with signals that all fail filtering → empty block."""

    def test_all_below_floor(self):
        em = _map(
            _sig("youtube_subscriber_count", 100, confidence=0.3),
            _sig("github_followers", 50, confidence=0.2),
        )
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows == []
        assert block.uplift_advisory is False
        assert block.platforms_found == []

    def test_empty_signals_list(self):
        block = PlatformPresenceExtractor.extract({"signals": []})
        assert block.rows == []
        assert block.uplift_advisory is False


class TestUnknownSignalKey:
    """Test 7 — Unknown signal key is silently skipped."""

    def test_unknown_key_no_crash(self):
        em = _map(
            {"key": "totally_unknown_signal", "value": 999, "confidence": 1.0,
             "source": "x", "osint_risk": False, "method": "api", "unit": None},
        )
        block = PlatformPresenceExtractor.extract(em)
        assert block.rows == []

    def test_unknown_key_mixed_with_known(self):
        em = _map(
            {"key": "totally_unknown_signal", "value": 999, "confidence": 1.0,
             "source": "x", "osint_risk": False, "method": "api", "unit": None},
            _sig("github_public_repos", 10, source="github"),
        )
        block = PlatformPresenceExtractor.extract(em)
        assert len(block.rows) == 1
        assert block.rows[0].platform == "github"


class TestNarrativeContent:
    """Test 8 — Narrative contains factual sentences; no forbidden wording."""

    FORBIDDEN_WORDS = {"signals", "confirms", "suggests"}

    def test_narrative_contains_platform_facts(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, source="youtube"),
            _sig("youtube_video_count", 61, source="youtube"),
            _sig("podcast_episode_count", 38, source="itunes"),
        )
        block = PlatformPresenceExtractor.extract(em)
        narrative_lower = block.narrative.lower()
        assert "youtube" in narrative_lower
        assert "podcast" in narrative_lower
        # Numbers should appear in narrative
        assert "4,200" in block.narrative
        assert "38" in block.narrative

    def test_no_forbidden_wording(self):
        em = _map(
            _sig("youtube_subscriber_count", 4200, source="youtube"),
            _sig("podcast_episode_count", 38, source="itunes"),
        )
        block = PlatformPresenceExtractor.extract(em)
        narrative_lower = block.narrative.lower()
        for word in self.FORBIDDEN_WORDS:
            assert word not in narrative_lower, f"Forbidden word found: {word!r}"

    def test_narrative_empty_for_no_platforms(self):
        block = PlatformPresenceExtractor.extract(None)
        assert block.narrative == ""

    def test_narrative_uses_handle_when_provided(self):
        em = _map(_sig("youtube_subscriber_count", 1000, source="youtube"))
        block = PlatformPresenceExtractor.extract(em, handle="@creator_x")
        assert block.narrative.startswith("@creator_x has a confirmed presence")

    def test_narrative_default_intro_this_creator(self):
        em = _map(_sig("youtube_subscriber_count", 1000, source="youtube"))
        block = PlatformPresenceExtractor.extract(em)
        assert block.narrative.startswith("This creator has a confirmed presence")


class TestTierOrdering:
    """Platform rows are ordered by tier: podcast → youtube → github → …"""

    def test_podcast_before_youtube(self):
        em = _map(
            _sig("youtube_subscriber_count", 100, source="youtube"),
            _sig("podcast_episode_count", 10, source="itunes"),
        )
        block = PlatformPresenceExtractor.extract(em)
        platforms = [r.platform for r in block.rows]
        assert platforms.index("podcast") < platforms.index("youtube")

    def test_github_before_substack(self):
        em = _map(
            _sig("substack_post_count", 5, source="substack"),
            _sig("github_public_repos", 10, source="github"),
        )
        block = PlatformPresenceExtractor.extract(em)
        platforms = [r.platform for r in block.rows]
        assert platforms.index("github") < platforms.index("substack")


class TestHandleResolution:
    """handle_or_id is populated from HANDLE_SIGNAL_MAP signals."""

    def test_youtube_handle_used(self):
        em = _map(
            _sig("youtube_subscriber_count", 1000, source="youtube"),
            _sig("youtube_handle", "@mychannel", source="youtube"),
        )
        block = PlatformPresenceExtractor.extract(em)
        yt_row = next(r for r in block.rows if r.platform == "youtube")
        assert yt_row.handle_or_id == "@mychannel"

    def test_podcast_itunes_suffix(self):
        em = _map(
            _sig("podcast_episode_count", 10, source="itunes"),
            {"key": "podcast_itunes_id", "value": "1234567890",
             "confidence": 0.3,  # any confidence — handle signals bypass floor
             "source": "itunes", "osint_risk": False, "method": "api", "unit": None},
        )
        block = PlatformPresenceExtractor.extract(em)
        pod_row = next(r for r in block.rows if r.platform == "podcast")
        assert pod_row.handle_or_id == "1234567890 (iTunes)"

    def test_fallback_to_platform_slug_when_no_handle(self):
        em = _map(_sig("github_public_repos", 5, source="github"))
        block = PlatformPresenceExtractor.extract(em)
        gh_row = next(r for r in block.rows if r.platform == "github")
        assert gh_row.handle_or_id == "github"


class TestPodcastLastEpisodeAt:
    """podcast_last_episode_at truncates to YYYY-MM."""

    def test_last_episode_truncated(self):
        em = _map(_sig("podcast_last_episode_at", "2024-03-15", source="itunes"))
        block = PlatformPresenceExtractor.extract(em)
        pod_row = next(r for r in block.rows if r.platform == "podcast")
        assert "Last: 2024-03" in pod_row.key_metric

    def test_last_episode_and_count_combined(self):
        em = _map(
            _sig("podcast_episode_count", 100, source="itunes"),
            _sig("podcast_last_episode_at", "2025-11-01", source="itunes"),
        )
        block = PlatformPresenceExtractor.extract(em)
        pod_row = next(r for r in block.rows if r.platform == "podcast")
        assert "100 episodes" in pod_row.key_metric
        assert "Last: 2025-11" in pod_row.key_metric
