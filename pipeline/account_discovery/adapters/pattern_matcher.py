"""URL-to-platform-handle pattern matcher adapter (spec-0018 §5).

Applies pure regex rules to map well-known platform URLs to their
canonical handle strings.  No HTTP calls are made.

Supported platforms: YouTube, GitHub, TikTok, Twitter/X, Twitch,
Reddit, Substack, and Spotify.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount

# ---------------------------------------------------------------------------
# Platform URL → handle extraction rules
# ---------------------------------------------------------------------------

_URL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (
        "youtube",
        "https://youtube.com/@{handle}",
        re.compile(
            r"(?:https?://)?(?:www\.)?youtube\.com/(?:@|c/|user/)?([A-Za-z0-9_.\-]{2,})",
            re.IGNORECASE,
        ),
    ),
    (
        "github",
        "https://github.com/{handle}",
        re.compile(
            r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.\-]{1,39})(?=[/?#\s]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "tiktok",
        "https://tiktok.com/@{handle}",
        re.compile(
            r"(?:https?://)?(?:www\.)?tiktok\.com/@?([A-Za-z0-9_.\-]{2,})(?=[/?#\s]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "twitter",
        "https://twitter.com/{handle}",
        re.compile(
            r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})(?=[/?#\s]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "twitch",
        "https://twitch.tv/{handle}",
        re.compile(
            r"(?:https?://)?(?:www\.)?twitch\.tv/([A-Za-z0-9_]{4,25})(?=[/?#\s]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "reddit",
        "https://reddit.com/u/{handle}",
        re.compile(
            r"(?:https?://)?(?:www\.)?reddit\.com/u(?:ser)?/([A-Za-z0-9_\-]{3,20})(?=[/?#\s]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "substack",
        "https://{handle}.substack.com",
        re.compile(
            r"(?:https?://)?([A-Za-z0-9_\-]{2,})\.substack\.com(?:[/?#]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "spotify",
        "https://open.spotify.com/user/{handle}",
        re.compile(
            r"(?:https?://)?open\.spotify\.com/user/([A-Za-z0-9_\-]{2,})",
            re.IGNORECASE,
        ),
    ),
]


def _match_url(url: str) -> list[DiscoveredAccount]:
    """Return DiscoveredAccount entries for each platform regex that matches *url*."""
    results: list[DiscoveredAccount] = []
    for platform, url_template, pattern in _URL_PATTERNS:
        m = pattern.match(url)
        if m is None:
            # Also attempt a search for substack which embeds differently
            m = pattern.search(url)
        if m is None:
            continue
        handle = m.group(1)
        profile_url = url_template.replace("{handle}", handle)
        results.append(
            DiscoveredAccount(
                account_id=str(uuid.uuid4()),
                platform=platform,
                handle=handle,
                profile_url=profile_url,
                confidence=0.9,
                method="url_pattern_match",
                source_adapter_id="pattern_matcher",
                attribution_chain=[
                    AttributionStep(
                        adapter_id="pattern_matcher",
                        from_entity_type="url",
                        from_entity_value=url[:500],
                        relationship="url_matches_platform_pattern",
                    )
                ],
                discovered_at=datetime.now(timezone.utc),
            )
        )
    return results


class PatternMatcher(DiscoveryAdapter):
    """Match platform URLs to canonical handles via regex rules.

    Supports YouTube, GitHub, TikTok, Twitter/X, Twitch, Reddit,
    Substack, and Spotify.  Pure in-memory — makes no network requests.
    """

    adapter_id = "pattern_matcher"
    display_name = "URL Pattern Matcher"
    requires = ["url"]
    produces = ["platform_handle"]
    priority = 3
    timeout_s = 5
    retry_max = 0
    data_category = "OPEN_DATA"
    tos_compliant = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list, config) -> list:  # type: ignore[override]
        """Match URL entities against platform patterns and return discovered accounts."""
        results: list[DiscoveredAccount] = []
        try:
            for entity in seed_entities:
                try:
                    etype = getattr(entity, "type", None) or (
                        entity.get("type") if isinstance(entity, dict) else None
                    )
                    evalue = getattr(entity, "value", None) or (
                        entity.get("value") if isinstance(entity, dict) else None
                    )
                    if etype != "url" or not evalue:
                        continue
                    results.extend(_match_url(str(evalue)))
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            return []
        return results
