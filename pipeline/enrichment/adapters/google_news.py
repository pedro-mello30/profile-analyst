"""Google News RSS adapter (Tier: medium, priority: 15)."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity

_NEWS_RSS_BASE = "https://news.google.com/rss/search"


class GoogleNewsAdapter(EnrichmentAdapter):
    adapter_id      = "google_news"
    display_name    = "Google News RSS"
    requires        = ["display_name", "handle"]
    produces        = []
    tier            = "medium"
    priority        = 15
    cost_usd        = 0.0
    timeout_s       = 10
    retry_max       = 2
    rate_limit_rpm  = 0
    ttl_hours       = 6
    min_confidence  = 0.5
    max_instances   = 1
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
            f"{_NEWS_RSS_BASE}?q={quote_plus(name)}"
            "&hl=pt-BR&gl=BR&ceid=BR:pt"
        )

        try:
            resp = requests.get(
                url,
                timeout=self.timeout_s,
                headers={"User-Agent": "profile-analyst/0.1"},
            )
            resp.raise_for_status()
            xml_text = resp.text
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"XML parse error: {exc}", cached=False, ran_at=now,
                cost_usd=0.0, duration_s=time.monotonic() - t0,
            )

        # RSS structure: <rss><channel><item>...</item></channel></rss>
        items = root.findall(".//item")
        now_dt = datetime.now(timezone.utc)
        cutoff = now_dt - timedelta(days=30)

        total_count = len(items)
        count_30d = 0
        latest_title: str | None = None
        latest_date: str | None = None
        first_item_processed = False

        for item in items:
            title_el = item.find("title")
            pub_date_el = item.find("pubDate")

            title = title_el.text.strip() if title_el is not None and title_el.text else None
            pub_date_raw = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else None

            # Track first item (most recent in RSS feeds)
            if not first_item_processed:
                latest_title = title
                if pub_date_raw:
                    try:
                        pub_dt = parsedate_to_datetime(pub_date_raw)
                        latest_date = pub_dt.date().isoformat()
                    except Exception:
                        latest_date = None
                first_item_processed = True

            # Count items in last 30 days
            if pub_date_raw:
                try:
                    pub_dt = parsedate_to_datetime(pub_date_raw)
                    # Make offset-aware for comparison
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt >= cutoff:
                        count_30d += 1
                except Exception:
                    pass

        signals: list[Signal] = [
            Signal(
                key="news_article_count_30d",
                value=count_30d,
                unit="count",
                confidence=0.8,
                method="scrape",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="news_article_count_total",
                value=total_count,
                unit="count",
                confidence=0.8,
                method="scrape",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="news_latest_headline",
                value=latest_title,
                unit=None,
                confidence=0.8,
                method="scrape",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="news_latest_date",
                value=latest_date,
                unit=None,
                confidence=0.8,
                method="scrape",
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
