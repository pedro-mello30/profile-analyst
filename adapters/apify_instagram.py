"""ApifyInstagramAdapter — fetches live public Instagram data via Apify (spec §3).

Legal basis: Meta v. Bright Data (2024) confirmed that logged-off scraping of public
Instagram data does not breach Meta's ToS. This adapter fetches only public profiles.
Requires APIFY_API_KEY environment variable.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from apify_client import ApifyClient

from adapters.base import SourceAdapter

_ACTOR_ID = "apify/instagram-scraper"

_MEDIA_TYPE_MAP = {
    "Image": "IMAGE",
    "Video": "REEL",
    "Sidecar": "CAROUSEL_ALBUM",
}


class ApifyInstagramAdapter(SourceAdapter):
    source_id = "apify_instagram"
    data_category = "PUBLIC_SCRAPE"
    # Meta v. Bright Data (2024): logged-off scraping of public data is lawful.
    tos_compliant = True
    auth_type = "API_KEY"
    requires_creator_consent = False
    calls_per_window = 100
    window_seconds = 3600
    available_fields = {
        "handle", "display_name", "bio", "website", "is_verified", "is_business",
        "account_type", "followers", "following", "post_count", "snapshot_at",
        "media_id", "media_type", "posted_at", "likes", "comments", "views",
        "caption", "hashtags", "mentions", "is_paid_partnership",
    }
    # saves and shares are not exposed by Instagram's public interface
    estimated_fields: set[str] = {"saves", "shares"}
    gdpr_basis = "LEGITIMATE_INTERESTS"
    requires_lia = False
    max_retention_days = 90
    deletion_on_request = True

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("APIFY_API_KEY")
        if not key:
            raise ValueError(
                "APIFY_API_KEY environment variable is required for ApifyInstagramAdapter. "
                "Get a free key at https://apify.com/"
            )
        self._client = ApifyClient(key)
        self._profile_cache: dict[str, dict] = {}
        self._posts_cache: dict[str, list] = {}

    def _run_actor(self, run_input: dict) -> list[dict]:
        run = self._client.actor(_ACTOR_ID).call(run_input=run_input)
        return list(self._client.dataset(run["defaultDatasetId"]).iterate_items())

    def _fetch_profile(self, handle: str) -> dict:
        if handle in self._profile_cache:
            return self._profile_cache[handle]
        items = self._run_actor({
            "directUrls": [f"https://www.instagram.com/{handle}/"],
            "resultsType": "details",
            "resultsLimit": 1,
        })
        if not items:
            raise ValueError(
                f"Apify returned no data for handle '{handle}'. "
                "The account may be private or the handle may not exist."
            )
        self._profile_cache[handle] = items[0]
        return items[0]

    def _fetch_posts(self, handle: str, limit: int) -> list[dict]:
        if handle in self._posts_cache:
            return self._posts_cache[handle][:limit]
        items = self._run_actor({
            "directUrls": [f"https://www.instagram.com/{handle}/"],
            "resultsType": "posts",
            "resultsLimit": limit,
        })
        self._posts_cache[handle] = items
        return items

    def fetch_profile(self, handle: str) -> dict:
        data = self._fetch_profile(handle)

        account_type = "BUSINESS" if data.get("isBusinessAccount") else "PERSONAL"

        location: str | None = None
        addr = data.get("businessAddressJson")
        if isinstance(addr, dict):
            location = addr.get("country_code")

        return {
            "handle": data.get("username", handle),
            "platform": "instagram",
            "profile_id": str(data["id"]) if data.get("id") else None,
            "display_name": data.get("fullName"),
            "bio": data.get("biography"),
            "website": data.get("externalUrl"),
            "is_verified": bool(data.get("isVerified", False)),
            "is_business": bool(data.get("isBusinessAccount", False)),
            "account_type": account_type,
            "location": location,
            "followers": int(data.get("followersCount", 0)),
            "following": int(data.get("followsCount", 0)),
            "post_count": int(data.get("postsCount", 0)),
            "snapshot_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def fetch_media(self, handle: str, limit: int = 20) -> list[dict]:
        posts = self._fetch_posts(handle, limit)
        mapped = [self._map_post(p) for p in posts]
        # Drop items that came back without a usable ID (e.g. private-account artefacts)
        return [m for m in mapped if m["media_id"]]

    def _map_post(self, post: dict) -> dict:
        media_type = _MEDIA_TYPE_MAP.get(post.get("type", "Image"), "IMAGE")

        ts = post.get("timestamp", "")
        if isinstance(ts, (int, float)):
            posted_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            posted_at = ts

        return {
            "media_id": str(post.get("id") or post.get("shortCode") or ""),
            "media_type": media_type,
            "posted_at": posted_at,
            "likes": post.get("likesCount"),
            "comments": post.get("commentsCount"),
            "saves": None,
            "shares": None,
            "views": post.get("videoViewCount"),
            "caption": post.get("caption"),
            "hashtags": post.get("hashtags") or [],
            "mentions": post.get("mentions") or [],
            "is_paid_partnership": bool(post.get("isSponsored", False)),
            "paid_partner_handle": None,
        }
