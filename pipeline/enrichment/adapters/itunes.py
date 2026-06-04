"""Apple iTunes Search / Podcast adapter (spec 0014 — fast tier, priority 20)."""
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
from pipeline.enrichment.entity import Entity, make_entity

_SOURCE = "itunes"
_SEARCH_URL = "https://itunes.apple.com/search"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ITunesAdapter(EnrichmentAdapter):
    """Apple iTunes Search / Podcast adapter. Public API; no auth required."""

    adapter_id = "itunes"
    display_name = "Apple iTunes Podcast Search"
    requires = ["display_name", "podcast_url", "podcast_itunes_id"]
    produces = ["podcast_itunes_id"]
    tier = "fast"
    priority = 20
    cost_usd = 0.0
    timeout_s = 10
    retry_max = 2
    rate_limit_rpm = 0
    ttl_hours = 72
    min_confidence = 0.5
    max_instances = 2
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

        # If we already have an itunes_id, we can look it up directly
        itunes_id_entity = next(
            (e for e in seed_entities if e.type == "podcast_itunes_id"), None
        )
        display_name_entity = next(
            (e for e in seed_entities if e.type == "display_name"), None
        )

        # Determine the search term: prefer display_name, fallback entities present for context
        search_term: str | None = None
        if display_name_entity:
            search_term = display_name_entity.value
        elif itunes_id_entity is None:
            # Only podcast_url available — no good way to search; skip
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[
                    Signal(key="podcast_found", value=False, unit=None,
                           confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
                ],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        result_data: dict | None = None

        if search_term:
            params = urllib.parse.urlencode({
                "term": search_term,
                "entity": "podcast",
                "limit": "3",
            })
            url = _SEARCH_URL + "?" + params
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    result_data = json.loads(resp.read().decode())
            except Exception as exc:
                return AdapterResult(
                    adapter_id=self.adapter_id, entities=[], signals=[],
                    error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                )

        results = (result_data or {}).get("results", [])
        if not results:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[
                    Signal(key="podcast_found", value=False, unit=None,
                           confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
                ],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        best = results[0]
        collection_id = best.get("collectionId")

        entities: list[Entity] = []
        _entity_signals: list[Signal] = []
        if collection_id is not None:
            raw_id = str(int(collection_id))
            try:
                depth = (display_name_entity or itunes_id_entity).depth + 1  # type: ignore[union-attr]
                entity = make_entity(
                    "podcast_itunes_id", raw_id,
                    source=_SOURCE,
                    confidence=0.85,
                    depth=depth,
                    discovered_at=now,
                )
                entities.append(entity)
            except ValueError:
                pass
            except Exception as e:
                _entity_signals.append(Signal(
                    key="entity_creation_error",
                    value=str(e),
                    unit=None,
                    confidence=0.0,
                    method="internal",
                    source=_SOURCE,
                    osint_risk=False,
                ))

        avg_rating = best.get("averageUserRating")
        signals = [
            *_entity_signals,
            Signal(key="podcast_found", value=True, unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="podcast_episode_count",
                   value=int(best["trackCount"]) if best.get("trackCount") is not None else None,
                   unit="episodes", confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="podcast_category",
                   value=best.get("primaryGenreName"),
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="podcast_language",
                   value=best.get("country"),  # iTunes uses "country" for language context
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="podcast_avg_rating",
                   value=float(avg_rating) if avg_rating is not None else None,
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="podcast_last_episode_at",
                   value=best.get("releaseDate"),
                   unit=None, confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=entities,
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
        )
