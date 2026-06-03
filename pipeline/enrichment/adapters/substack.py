"""Substack publication stats adapter (Tier: medium, priority: 35)."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import requests

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity

_SLUG_RE = re.compile(r"https?://([a-z0-9-]+)\.substack\.com", re.IGNORECASE)


class SubstackAdapter(EnrichmentAdapter):
    adapter_id      = "substack"
    display_name    = "Substack publication stats"
    requires        = ["substack_url"]
    produces        = []
    tier            = "medium"
    priority        = 35
    cost_usd        = 0.0
    timeout_s       = 15
    retry_max       = 1
    rate_limit_rpm  = 0
    ttl_hours       = 48
    min_confidence  = 0.7
    max_instances   = 2
    osint_risk      = False
    secrets_required = []
    gdpr_basis      = "LEGITIMATE_INTERESTS"
    data_category   = "PUBLIC_SCRAPE"
    tos_compliant   = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        substack_url = seed_entities[0].value

        # Extract slug from URL like https://{slug}.substack.com
        match = _SLUG_RE.match(substack_url)
        if not match:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"Cannot extract slug from substack_url: {substack_url!r}",
                cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        slug = match.group(1)
        api_url = f"https://{slug}.substack.com/api/v1/posts?limit=10"

        try:
            resp = requests.get(
                api_url,
                timeout=self.timeout_s,
                headers={"User-Agent": "profile-analyst/0.1"},
            )
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        if resp.status_code == 404:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"Substack publication not found: {slug}",
                cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        if not resp.ok:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"Substack API HTTP {resp.status_code}: {resp.text[:200]}",
                cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        try:
            posts: list[dict] = resp.json()
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"JSON parse error: {exc}", cached=False, ran_at=now,
                cost_usd=0.0, duration_s=time.monotonic() - t0,
            )

        if not isinstance(posts, list):
            posts = []

        now_dt = datetime.now(timezone.utc)
        cutoff = now_dt - timedelta(days=30)

        has_paid_tier = False
        recent_count = 0

        for post in posts:
            # Check for paid-only content
            audience = post.get("audience") or ""
            if audience == "paid":
                has_paid_tier = True

            # Check publish date for last 30 days
            pub_date_raw = (
                post.get("post_date")
                or post.get("published_at")
                or post.get("publishedAt")
                or ""
            )
            if pub_date_raw:
                try:
                    pub_dt = datetime.fromisoformat(
                        str(pub_date_raw).replace("Z", "+00:00")
                    )
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt >= cutoff:
                        recent_count += 1
                except (ValueError, TypeError):
                    pass

        signals: list[Signal] = [
            Signal(
                key="substack_post_count",
                value=len(posts),
                unit="count",
                confidence=0.9,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="substack_has_paid_tier",
                value=has_paid_tier,
                unit=None,
                confidence=0.9,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="substack_recent_post_count_30d",
                value=recent_count,
                unit="count",
                confidence=0.9,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=[],
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
            duration_s=time.monotonic() - t0,
        )
