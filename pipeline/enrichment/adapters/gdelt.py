"""GDELT news-mention adapter (Tier: medium, priority: 10)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity

_GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltAdapter(EnrichmentAdapter):
    """GDELT open-data news-mention adapter. Public API; no auth required."""

    adapter_id      = "gdelt"
    display_name    = "GDELT — news mentions"
    requires        = ["display_name", "handle"]
    produces        = []
    tier            = "medium"
    priority        = 10
    cost_usd        = 0.0
    timeout_s       = 15
    retry_max       = 2
    rate_limit_rpm  = 0
    ttl_hours       = 6
    min_confidence  = 0.5
    max_instances   = 1
    osint_risk      = False
    secrets_required = []
    gdpr_basis      = "LEGITIMATE_INTERESTS"
    data_category   = "OPEN_DATA"
    tos_compliant   = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Prefer display_name; fall back to handle
        name: str | None = None
        for ent in seed_entities:
            if ent.type == "display_name":
                name = ent.value
                break
        if name is None:
            for ent in seed_entities:
                if ent.type == "handle":
                    name = ent.value
                    break
        if name is None:
            name = seed_entities[0].value

        url = (
            f"{_GDELT_BASE}?query={quote_plus(name)}"
            "&mode=artlist&format=json&maxrecords=75"
        )

        try:
            resp = requests.get(
                url,
                timeout=self.timeout_s,
                headers={"User-Agent": "profile-analyst/0.1"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        articles: list[dict] = data.get("articles") or []
        article_count = len(articles)

        tones: list[float] = []
        source_countries: list[str] = []
        seen_countries: set[str] = set()

        for article in articles:
            # Tone field
            tone_val = article.get("tone")
            if tone_val is not None:
                try:
                    tones.append(float(tone_val))
                except (TypeError, ValueError):
                    pass

            # Source country
            country = article.get("sourceCountry") or article.get("sourcecountry") or ""
            if country and country not in seen_countries:
                seen_countries.add(country)
                source_countries.append(country)

        tone_avg = (sum(tones) / len(tones)) if tones else 0.0
        positive_pct = (
            (sum(1 for t in tones if t > 0) / len(tones) * 100.0) if tones else 0.0
        )
        # Cap source countries at 10
        source_countries = source_countries[:10]

        signals: list[Signal] = [
            Signal(
                key="gdelt_mention_count",
                value=article_count,
                unit="count",
                confidence=0.8,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="gdelt_tone_avg",
                value=round(tone_avg, 4),
                unit=None,
                confidence=0.7,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="gdelt_positive_pct",
                value=round(positive_pct, 2),
                unit="percent",
                confidence=0.7,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="gdelt_source_countries",
                value=source_countries,
                unit=None,
                confidence=0.8,
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
