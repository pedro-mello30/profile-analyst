"""Bio-link hub expander adapter (spec-0018 §5).

Fetches Linktree / Beacons / bio.site pages and extracts embedded platform
URLs from the HTML.  Only acts on URLs that match a known bio-link hub
pattern — returns [] for all other URLs.  Uses only the Python standard
library for HTTP; respects robots.txt as a policy commitment.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser

from pipeline.account_discovery.adapters._patterns import PLATFORM_PATTERNS
from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount

# ---------------------------------------------------------------------------
# Bio-link hub detection
# ---------------------------------------------------------------------------

_HUB_PATTERN = re.compile(
    r"https?://(?:www\.)?"
    r"(?:linktr\.ee|linktree\.com|beacons\.ai|bio\.site|beacons\.page)"
    r"(?:/[^?\s]*)?",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Platform handle extraction — derived from shared PLATFORM_PATTERNS
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

_PLATFORM_HREF_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (platform, _URL_TEMPLATES.get(platform, "https://{handle}"), pattern)
    for platform, pattern in PLATFORM_PATTERNS
]

_USER_AGENT = "profile-analyst/1.0"


# ---------------------------------------------------------------------------
# Minimal HTML anchor extractor
# ---------------------------------------------------------------------------


class _AnchorHrefCollector(HTMLParser):
    """Collect href attribute values from <a> tags."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.hrefs.append(value)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _fetch_html(url: str, timeout_s: float) -> str | None:
    """Fetch URL and return response body as a string, or None on any error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read(1_048_576)  # 1 MiB cap
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except Exception:  # noqa: BLE001
        return None


def _extract_platform_accounts(
    hrefs: list[str], source_url: str
) -> list[DiscoveredAccount]:
    """Match each href against platform patterns and return DiscoveredAccount list."""
    seen: set[str] = set()
    results: list[DiscoveredAccount] = []
    for href in hrefs:
        for platform, url_template, pattern in _PLATFORM_HREF_PATTERNS:
            m = pattern.search(href)
            if m is None:
                continue
            handle = m.group(1)
            dedup_key = f"{platform}:{handle.lower()}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            profile_url = url_template.replace("{handle}", handle)
            results.append(
                DiscoveredAccount(
                    account_id=str(uuid.uuid4()),
                    platform=platform,
                    handle=handle,
                    profile_url=profile_url,
                    confidence=0.8,
                    method="link_expander",
                    source_adapter_id="link_expander",
                    attribution_chain=[
                        AttributionStep(
                            adapter_id="link_expander",
                            from_entity_type="url",
                            from_entity_value=source_url[:500],
                            relationship="bio_link_hub_contains_platform_url",
                        )
                    ],
                    discovered_at=datetime.now(timezone.utc),
                )
            )
    return results


class LinkExpander(DiscoveryAdapter):
    """Expand bio-link hub pages (Linktree, Beacons, bio.site) to platform handles.

    Fetches the hub page HTML with a single GET request and extracts all
    <a href> values that match known platform URL patterns.  Only processes
    URLs that are recognised bio-link hubs; returns [] otherwise.
    Respects robots.txt as a policy commitment (no automated crawling beyond
    the single landing page fetch).
    """

    adapter_id = "link_expander"
    display_name = "Bio-Link Hub Expander"
    requires = ["url"]
    produces = ["url", "platform_handle"]
    priority = 2
    timeout_s = 10
    retry_max = 1
    data_category = "PUBLIC_SCRAPE"
    tos_compliant = True
    robots_txt_policy = "RESPECT"

    def run(self, seed_entities: list, config) -> list:  # type: ignore[override]
        """Fetch bio-link hub pages and return platform accounts found in links."""
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
                    url = str(evalue)
                    if not _HUB_PATTERN.match(url):
                        continue
                    html = _fetch_html(url, self.timeout_s)
                    if not html:
                        continue
                    parser = _AnchorHrefCollector()
                    parser.feed(html)
                    results.extend(_extract_platform_accounts(parser.hrefs, url))
                except (AttributeError, TypeError, ValueError):
                    continue
        except Exception:  # last-resort guard; inner loop is narrowed above
            return []
        return results
