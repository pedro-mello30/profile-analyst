"""YouTube Data API v3 adapter (spec 0014 — fast tier, priority 10)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity

_SOURCE = "youtube"
_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class YouTubeAdapter(EnrichmentAdapter):
    """YouTube Data API v3 adapter.

    Without YOUTUBE_API_KEY, uses unauthenticated requests (lower quota and reliability).
    With key, enforces configured rate_limit_rpm.
    """

    adapter_id = "youtube"
    display_name = "YouTube Data API v3"
    requires = ["youtube_channel_id", "youtube_handle"]
    produces = []
    tier = "fast"
    priority = 10
    cost_usd = 0.0
    timeout_s = 15
    retry_max = 2
    rate_limit_rpm = 0
    ttl_hours = 24
    min_confidence = 0.6
    max_instances = 3
    osint_risk = False
    secrets_required = []
    gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_API"
    tos_compliant = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = _now()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        key = config.secrets.get("YOUTUBE_API_KEY", "")

        channel_id_entity = next(
            (e for e in seed_entities if e.type == "youtube_channel_id"), None
        )
        handle_entity = next(
            (e for e in seed_entities if e.type == "youtube_handle"), None
        )

        data: dict | None = None
        error_msg: str | None = None

        # Try channel_id first, then handle
        for entity, param_name in [
            (channel_id_entity, "id"),
            (handle_entity, "forHandle"),
        ]:
            if entity is None:
                continue
            params: dict[str, str] = {
                "part": "snippet,statistics,topicDetails",
                param_name: entity.value,
            }
            if key:
                params["key"] = key
            url = _CHANNELS_URL + "?" + urllib.parse.urlencode(params)
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    data = json.loads(resp.read().decode())
                if data.get("items"):
                    break  # found a result
                data = None  # empty items — try next seed
            except Exception as exc:
                error_msg = str(exc)
                data = None

        if data is None or not data.get("items"):
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=error_msg or "no channel found",
                cached=False, ran_at=now, cost_usd=0.0,
            )

        item = data["items"][0]
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        topic_details = item.get("topicDetails", {})

        # Extract last path segment from topic URLs
        topic_categories: list[str] = []
        for topic_url in topic_details.get("topicCategories", []):
            segment = topic_url.rstrip("/").rsplit("/", 1)[-1].replace("_", " ")
            if segment and segment not in topic_categories:
                topic_categories.append(segment)

        signals = [
            Signal(key="youtube_api_authenticated", value=bool(key), unit=None,
                   confidence=1.0, method="config", source=_SOURCE, osint_risk=False),
            Signal(key="youtube_subscriber_count",
                   value=_int_or_none(statistics.get("subscriberCount")),
                   unit="subscribers", confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="youtube_video_count",
                   value=_int_or_none(statistics.get("videoCount")),
                   unit="videos", confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="youtube_view_count_total",
                   value=_int_or_none(statistics.get("viewCount")),
                   unit="views", confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="youtube_country",
                   value=snippet.get("country"),
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="youtube_published_at",
                   value=snippet.get("publishedAt"),
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="youtube_topics",
                   value=topic_categories,
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=[],
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
        )
