"""Google Knowledge Graph Search adapter (spec 0014 — fast tier, priority 5)."""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity, make_entity

_SOURCE = "knowledge_graph"
_KG_URL = "https://kgsearch.googleapis.com/v1/entities:search"
_WIKIDATA_RE = re.compile(r"wikidata\.org/wiki/(Q\d+)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class KnowledgeGraphAdapter(EnrichmentAdapter):
    adapter_id = "knowledge_graph"
    display_name = "Google Knowledge Graph"
    requires = ["display_name", "handle"]
    produces = ["wikidata_id"]
    tier = "fast"
    priority = 5
    cost_usd = 0.0
    timeout_s = 10
    retry_max = 2
    rate_limit_rpm = 0
    ttl_hours = 168
    min_confidence = 0.5
    max_instances = 1
    osint_risk = False
    secrets_required = []
    gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_API"
    tos_compliant = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = _now()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        # Prefer display_name over handle for the query
        name_entity = next(
            (e for e in seed_entities if e.type == "display_name"), None
        ) or next(
            (e for e in seed_entities if e.type == "handle"), None
        )
        if name_entity is None:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="no usable seed entity", cached=False, ran_at=now, cost_usd=0.0,
            )

        query_name = name_entity.value
        key = config.secrets.get("GOOGLE_KG_KEY", "")

        params: dict[str, str] = {
            "query": query_name,
            "types": "Person",
            "limit": "3",
        }
        if key:
            params["key"] = key

        url = _KG_URL + "?" + urllib.parse.urlencode(params)

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
            )

        items = data.get("itemListElement", [])
        if not items:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[
                    Signal(key="kg_entity_found", value=False, unit=None,
                           confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
                ],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        # Determine maximum score across all items for normalising confidence
        scores = [item.get("resultScore", 0.0) for item in items]
        max_score = max(scores) if scores else 1.0
        if max_score == 0.0:
            max_score = 1.0

        best_item = items[0]
        result_node = best_item.get("result", {})
        best_score = best_item.get("resultScore", 0.5)
        confidence = min(1.0, best_score / max_score)

        # Extract wikidata QID from sameAs list
        same_as = result_node.get("sameAs", [])
        if isinstance(same_as, str):
            same_as = [same_as]
        qid: str | None = None
        for url_entry in same_as:
            m = _WIKIDATA_RE.search(url_entry)
            if m:
                qid = m.group(1)
                break

        entities: list[Entity] = []
        if qid:
            try:
                entity = make_entity(
                    "wikidata_id", qid,
                    source=_SOURCE,
                    confidence=confidence,
                    depth=(name_entity.depth + 1),
                    discovered_at=now,
                )
                entities.append(entity)
            except Exception:
                pass  # malformed QID — skip silently

        entity_types = result_node.get("@type", [])
        if isinstance(entity_types, str):
            entity_types = [entity_types]

        signals = [
            Signal(key="kg_entity_found", value=True, unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="kg_description",
                   value=result_node.get("description", ""),
                   unit=None, confidence=confidence, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="kg_entity_types", value=entity_types, unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="kg_relevance_score", value=float(best_score), unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
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
