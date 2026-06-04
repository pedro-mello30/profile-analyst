"""Linktree / bio-link scrape adapter (Tier 0, seed)."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import requests

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity, make_entity

# Compiled regexes for platform extraction
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("youtube_channel_id", re.compile(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})")),
    ("youtube_handle",     re.compile(r"youtube\.com/@([a-zA-Z0-9._-]{3,30})")),
    ("github_handle",      re.compile(r"github\.com/([a-zA-Z0-9-]{1,39})(?:/|$)")),
    ("tiktok_handle",      re.compile(r"tiktok\.com/@([a-zA-Z0-9._]{1,24})")),
    ("twitter_handle",     re.compile(r"(?:twitter|x)\.com/([a-zA-Z0-9_]{1,15})")),
    ("twitch_handle",      re.compile(r"twitch\.tv/([a-z0-9_]{4,25})")),
]

_EMAIL_RE         = re.compile(r"mailto:([^\s\"'>]+)")
_SUBSTACK_RE      = re.compile(r"(https://[a-z0-9-]+\.substack\.com)")
_SPOTIFY_PODCAST_RE = re.compile(r"(https://open\.spotify\.com/(?:show|episode)/[a-zA-Z0-9]+)")


class LinktreeAdapter(EnrichmentAdapter):
    """Linktree / bio-link page scraper. Scrapes the public bio-link URL; robots.txt is respected."""

    adapter_id     = "linktree"
    display_name   = "Linktree / Bio-link"
    requires       = ["bio_url"]
    produces       = [
        "email", "domain", "youtube_channel_id", "youtube_handle",
        "tiktok_handle", "twitter_handle", "instagram_handle",
        "podcast_url", "substack_url", "website_url",
        "github_handle", "twitch_handle", "spotify_artist_id",
    ]
    tier           = "seed"
    priority       = 1
    cost_usd       = 0.0
    timeout_s      = 15
    retry_max      = 2
    rate_limit_rpm = 0
    ttl_hours      = 24
    min_confidence = 0.8
    max_instances  = 1
    osint_risk     = False
    secrets_required = []
    gdpr_basis     = "LEGITIMATE_INTERESTS"
    data_category  = "PUBLIC_SCRAPE"
    tos_compliant  = True
    robots_txt_policy = "RESPECT"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0  = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        seed   = seed_entities[0]
        url    = seed.value
        depth  = seed.depth + 1

        try:
            resp = requests.get(
                url,
                timeout=self.timeout_s,
                headers={"User-Agent": "profile-analyst/0.1"},
                allow_redirects=True,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        entities: list[Entity] = []
        _entity_signals: list[Signal] = []
        platforms_seen: set[str] = set()

        # ── Platform handle / channel patterns ────────────────────────────────
        for entity_type, pattern in _PATTERNS:
            for match in pattern.finditer(html):
                raw = match.group(1)
                try:
                    ent = make_entity(
                        entity_type, raw,
                        source="linktree", confidence=0.9, depth=depth,
                        discovered_at=now,
                    )
                    entities.append(ent)
                    platforms_seen.add(entity_type)
                except ValueError:
                    pass
                except Exception as e:
                    _entity_signals.append(Signal(
                        key="entity_creation_error",
                        value=str(e),
                        unit=None,
                        confidence=0.0,
                        method="internal",
                        source=self.adapter_id,
                        osint_risk=False,
                    ))

        # ── Email (mailto:) ───────────────────────────────────────────────────
        for match in _EMAIL_RE.finditer(html):
            raw = match.group(1)
            try:
                ent = make_entity(
                    "email", raw,
                    source="linktree", confidence=0.9, depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
                platforms_seen.add("email")
            except ValueError:
                pass
            except Exception as e:
                _entity_signals.append(Signal(
                    key="entity_creation_error",
                    value=str(e),
                    unit=None,
                    confidence=0.0,
                    method="internal",
                    source=self.adapter_id,
                    osint_risk=False,
                ))

        # ── Substack URLs ─────────────────────────────────────────────────────
        for match in _SUBSTACK_RE.finditer(html):
            raw = match.group(1)
            try:
                ent = make_entity(
                    "substack_url", raw,
                    source="linktree", confidence=0.9, depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
                platforms_seen.add("substack_url")
            except ValueError:
                pass
            except Exception as e:
                _entity_signals.append(Signal(
                    key="entity_creation_error",
                    value=str(e),
                    unit=None,
                    confidence=0.0,
                    method="internal",
                    source=self.adapter_id,
                    osint_risk=False,
                ))

        # ── Spotify podcast / show URLs ───────────────────────────────────────
        for match in _SPOTIFY_PODCAST_RE.finditer(html):
            raw = match.group(1)
            try:
                ent = make_entity(
                    "podcast_url", raw,
                    source="linktree", confidence=0.9, depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
                platforms_seen.add("podcast_url")
            except Exception:
                pass

        # De-duplicate entities by (type, value)
        seen_pairs: set[tuple[str, str]] = set()
        deduped: list[Entity] = []
        for ent in entities:
            key = (ent.type, ent.value)
            if key not in seen_pairs:
                seen_pairs.add(key)
                deduped.append(ent)

        signals = [
            *_entity_signals,
            Signal(
                key="bio_link_platform_count",
                value=len(platforms_seen),
                unit="count",
                confidence=1.0,
                method="scrape",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="bio_link_platforms",
                value=sorted(platforms_seen),
                unit=None,
                confidence=1.0,
                method="scrape",
                source=self.adapter_id,
                osint_risk=False,
            ),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=deduped,
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
            duration_s=time.monotonic() - t0,
        )
