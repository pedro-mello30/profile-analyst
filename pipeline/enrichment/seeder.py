"""Pool seeder — seeds EntityPool from raw/discovery artifacts (spec-0019 §4)."""
from __future__ import annotations

import logging

from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool

logger = logging.getLogger(__name__)

# Platform → entity type mapping for discovery accounts
# Entity types sourced from ENTITY_TYPES in entity.py
_PLATFORM_MAP: dict[str, str] = {
    "youtube":   "youtube_handle",
    "github":    "github_handle",
    "spotify":   "spotify_artist_id",
    "twitch":    "twitch_handle",
    "reddit":    "reddit_username",
    "tiktok":    "tiktok_handle",
    "twitter":   "twitter_handle",
    "substack":  "substack_url",
    "linkedin":  "linkedin_url",
    "instagram": "instagram_handle",
}

_FALLBACK_TYPE = "website_url"


def seed_from_raw(raw_doc: dict, pool: EntityPool) -> None:
    """Seed EntityPool from 01-raw.json (spec-0019 §4.1).

    Seeds: handle from raw_profile.username, bio_url from raw_profile.bio_url,
    email from raw_profile.email — all at depth=0, confidence=1.0.
    Silently skips invalid values.
    """
    raw_profile = raw_doc.get("raw_profile") or {}

    seeds = [
        ("handle",  raw_profile.get("username")),
        ("bio_url", raw_profile.get("bio_url")),
        ("email",   raw_profile.get("email")),
    ]

    for entity_type, raw_value in seeds:
        if not raw_value:
            continue
        try:
            entity = make_entity(
                entity_type,
                str(raw_value),
                source="seed:raw",
                confidence=1.0,
                depth=0,
            )
            pool.add(entity)
        except Exception as exc:
            logger.debug(
                "seed_from_raw: skipping %s=%r — %s", entity_type, raw_value, exc
            )


def seed_from_discovery(discovery_doc: dict | None, pool: EntityPool) -> None:
    """Seed EntityPool from 00-discovery.json at depth=1 (spec-0019 §4.2).

    Each DiscoveredAccount becomes a seed entity at depth=1.
    Unknown platforms fall back to entity type 'website_url'.
    None or empty dict → no-op.
    """
    if not discovery_doc:
        return

    accounts = discovery_doc.get("discovered_accounts") or []

    for account in accounts:
        platform = str(account.get("platform") or "").lower()
        handle = account.get("handle") or ""
        confidence = float(account.get("confidence") or 0.5)
        account_id = account.get("account_id") or "discovery"

        entity_type = _PLATFORM_MAP.get(platform, _FALLBACK_TYPE)

        try:
            entity = make_entity(
                entity_type,
                str(handle),
                source=f"seed:discovery:{account_id}",
                confidence=confidence,
                depth=1,
            )
            pool.add(entity)
        except Exception as exc:
            logger.debug(
                "seed_from_discovery: skipping platform=%r handle=%r — %s",
                platform, handle, exc,
            )
