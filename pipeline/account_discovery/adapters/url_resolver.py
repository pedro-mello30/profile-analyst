"""Redirect-following URL resolver adapter (spec-0018 §5).

Issues an HTTP HEAD request to resolve the final URL after any redirect
chain, then delegates to the PatternMatcher logic to identify the
resulting platform handle.  Returns [] if no redirect occurred or if
the HTTP request fails.
"""
from __future__ import annotations

import http.client
import re
import urllib.parse
import uuid
from datetime import datetime, timezone

from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount

_USER_AGENT = "profile-analyst/1.0"
_MAX_REDIRECTS = 10

# ---------------------------------------------------------------------------
# Platform matching (inline, avoids circular import with pattern_matcher)
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


def _match_platform(url: str) -> tuple[str, str, str] | None:
    """Return (platform, handle, profile_url) for the first matching pattern, or None."""
    for platform, url_template, pattern in _URL_PATTERNS:
        m = pattern.search(url)
        if m:
            handle = m.group(1)
            return platform, handle, url_template.replace("{handle}", handle)
    return None


def _resolve_redirect(url: str, timeout_s: float) -> str | None:
    """Follow HEAD redirects and return the final URL, or None if no redirect / error."""
    try:
        parsed = urllib.parse.urlparse(url)
        current_url = url
        visited: list[str] = [url]

        for _ in range(_MAX_REDIRECTS):
            p = urllib.parse.urlparse(current_url)
            if p.scheme == "https":
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    p.netloc, timeout=timeout_s
                )
            else:
                conn = http.client.HTTPConnection(p.netloc, timeout=timeout_s)

            path = p.path or "/"
            if p.query:
                path = f"{path}?{p.query}"

            conn.request(
                "HEAD",
                path,
                headers={"User-Agent": _USER_AGENT, "Host": p.netloc},
            )
            resp = conn.getresponse()
            conn.close()

            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location", "")
                if not location:
                    break
                # Resolve relative redirects
                next_url = urllib.parse.urljoin(current_url, location)
                if next_url == current_url or next_url in visited:
                    break
                visited.append(next_url)
                current_url = next_url
            else:
                break

        final = visited[-1]
        return final if final != url else None

    except Exception:  # noqa: BLE001
        return None


class UrlResolver(DiscoveryAdapter):
    """Resolve URL redirects and identify the final platform via pattern matching.

    Issues an HTTP HEAD request and follows the redirect chain to find the
    canonical destination URL.  If a redirect occurred, the final URL is
    matched against known platform patterns to extract the handle.
    Returns [] if the URL does not redirect or if the HTTP request fails.
    """

    adapter_id = "url_resolver"
    display_name = "URL Redirect Resolver"
    requires = ["url"]
    produces = ["platform_handle"]
    priority = 4
    timeout_s = 10
    retry_max = 1
    data_category = "PUBLIC_SCRAPE"
    tos_compliant = True
    robots_txt_policy = "RESPECT"

    def run(self, seed_entities: list, config) -> list:  # type: ignore[override]
        """Resolve redirects for URL entities and match the final URL to a platform."""
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
                    original_url = str(evalue)
                    final_url = _resolve_redirect(original_url, self.timeout_s)
                    if not final_url:
                        continue
                    match = _match_platform(final_url)
                    if not match:
                        continue
                    platform, handle, profile_url = match
                    results.append(
                        DiscoveredAccount(
                            account_id=str(uuid.uuid4()),
                            platform=platform,
                            handle=handle,
                            profile_url=profile_url,
                            confidence=0.85,
                            method="url_redirect_resolve",
                            source_adapter_id="url_resolver",
                            attribution_chain=[
                                AttributionStep(
                                    adapter_id="url_resolver",
                                    from_entity_type="url",
                                    from_entity_value=original_url[:500],
                                    relationship="url_redirects_to_platform",
                                )
                            ],
                            discovered_at=datetime.now(timezone.utc),
                        )
                    )
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            return []
        return results
