"""Bio-text parser adapter for account discovery (spec-0018 §5).

Parses free-form bio text using regular expressions to extract cross-platform
handles for YouTube, GitHub, TikTok, Twitter/X, and Twitch.  No HTTP calls
are made — all work is purely in-memory string matching.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from pipeline.account_discovery.adapters._patterns import PLATFORM_PATTERNS
from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount

# ---------------------------------------------------------------------------
# Platform extraction rules — URL templates keyed by platform name
# ---------------------------------------------------------------------------

_URL_TEMPLATES: dict[str, str] = {
    "youtube":  "https://youtube.com/@{handle}",
    "github":   "https://github.com/{handle}",
    "tiktok":   "https://tiktok.com/@{handle}",
    "twitter":  "https://twitter.com/{handle}",
    "twitch":   "https://twitch.tv/{handle}",
    "reddit":   "https://reddit.com/u/{handle}",
    "substack": "https://{handle}.substack.com",
    "spotify":  "https://open.spotify.com/artist/{handle}",
}

# bio_parser only handles a subset of platforms (no substack/spotify in bio text)
_BIO_PLATFORMS = {"youtube", "github", "tiktok", "twitter", "twitch"}
_PLATFORM_PATTERNS = [
    (platform, _URL_TEMPLATES[platform], pattern)
    for platform, pattern in PLATFORM_PATTERNS
    if platform in _BIO_PLATFORMS
]


def _extract_accounts(bio_text: str, source_type: str, source_value: str) -> list[DiscoveredAccount]:
    """Extract DiscoveredAccount entries from a single bio text string."""
    results: list[DiscoveredAccount] = []
    for platform, url_template, pattern in _PLATFORM_PATTERNS:
        for match in pattern.finditer(bio_text):
            handle = match.group(1)
            profile_url = url_template.replace("{handle}", handle)
            account = DiscoveredAccount(
                account_id=str(uuid.uuid4()),
                platform=platform,
                handle=handle,
                profile_url=profile_url,
                confidence=0.85,
                method="bio_parse",
                source_adapter_id="bio_parser",
                attribution_chain=[
                    AttributionStep(
                        adapter_id="bio_parser",
                        from_entity_type=source_type,
                        from_entity_value=source_value[:200],
                        relationship="bio_text_contains_handle",
                    )
                ],
                discovered_at=datetime.now(timezone.utc),
            )
            results.append(account)
    return results


class BioParsing(DiscoveryAdapter):
    """Parse bio text to extract cross-platform handles using regex.

    Supports YouTube, GitHub, TikTok, Twitter/X, and Twitch.
    Pure in-memory — makes no network requests.
    """

    adapter_id = "bio_parser"
    display_name = "Bio Text Parser"
    requires = ["bio_text"]
    produces = ["url", "platform_handle"]
    priority = 1
    timeout_s = 5
    retry_max = 0
    data_category = "PUBLIC_API"
    tos_compliant = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list, config) -> list:  # type: ignore[override]
        """Parse bio text from seed entities and return discovered accounts."""
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
                    if etype != "bio_text" or not evalue:
                        continue
                    results.extend(_extract_accounts(str(evalue), etype, str(evalue)))
                except (AttributeError, TypeError, ValueError):
                    continue
        except Exception:  # last-resort guard; inner loop is narrowed above
            return []
        return results
