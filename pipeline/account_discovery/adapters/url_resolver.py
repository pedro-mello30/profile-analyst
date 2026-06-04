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

from pipeline.account_discovery.adapters._patterns import PLATFORM_PATTERNS
from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount

_USER_AGENT = "profile-analyst/1.0"
_MAX_REDIRECTS = 10

# ---------------------------------------------------------------------------
# Platform matching — derived from shared PLATFORM_PATTERNS
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

_URL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (platform, _URL_TEMPLATES.get(platform, "https://{handle}"), pattern)
    for platform, pattern in PLATFORM_PATTERNS
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

            try:
                conn.request(
                    "HEAD",
                    path,
                    headers={"User-Agent": _USER_AGENT, "Host": p.netloc},
                )
                resp = conn.getresponse()
                status = resp.status
                location = resp.getheader("Location", "")
            finally:
                conn.close()

            if status in (301, 302, 303, 307, 308):
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

    def _resolve_redirect(self, url: str) -> str | None:
        """Instance-level wrapper around the module-level redirect resolver.

        Exposed as an instance method to allow test-time patching via
        ``unittest.mock.patch.object``.
        """
        return _resolve_redirect(url, self.timeout_s)

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
                    final_url = self._resolve_redirect(original_url)
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
