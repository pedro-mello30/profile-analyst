"""Wikidata SPARQL adapter (spec 0014 — fast tier, priority 15)."""
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

_SOURCE = "wikidata"
_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_USER_AGENT = "profile-analyst/0.1 (https://github.com/example)"

_SPARQL_TEMPLATE = """\
SELECT ?occupationLabel ?nationalityLabel ?employerLabel ?awardLabel WHERE {{
  OPTIONAL {{ wd:{qid} wdt:P106 ?occupation. ?occupation rdfs:label ?occupationLabel. FILTER(LANG(?occupationLabel)="en") }}
  OPTIONAL {{ wd:{qid} wdt:P27 ?nationality. ?nationality rdfs:label ?nationalityLabel. FILTER(LANG(?nationalityLabel)="en") }}
  OPTIONAL {{ wd:{qid} wdt:P108 ?employer. ?employer rdfs:label ?employerLabel. FILTER(LANG(?employerLabel)="en") }}
  OPTIONAL {{ wd:{qid} wdt:P166 ?award. ?award rdfs:label ?awardLabel. FILTER(LANG(?awardLabel)="en") }}
}} LIMIT 20"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WikidataAdapter(EnrichmentAdapter):
    """Wikidata SPARQL adapter. Public SPARQL endpoint; no auth required."""

    adapter_id = "wikidata"
    display_name = "Wikidata SPARQL"
    requires = ["wikidata_id"]
    produces = []
    tier = "fast"
    priority = 15
    cost_usd = 0.0
    timeout_s = 15
    retry_max = 2
    rate_limit_rpm = 0
    ttl_hours = 168
    min_confidence = 0.5
    max_instances = 1
    osint_risk = False
    secrets_required = []
    gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "OPEN_DATA"
    tos_compliant = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = _now()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        wikidata_entity = next(
            (e for e in seed_entities if e.type == "wikidata_id"), None
        )
        if wikidata_entity is None:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="no wikidata_id seed entity", cached=False, ran_at=now, cost_usd=0.0,
            )

        qid = wikidata_entity.value  # already normalised to uppercase "Q\d+"
        sparql = _SPARQL_TEMPLATE.format(qid=qid)
        params = urllib.parse.urlencode({"query": sparql, "format": "json"})
        full_url = _SPARQL_ENDPOINT + "?" + params

        try:
            req = urllib.request.Request(
                full_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
            )

        bindings = data.get("results", {}).get("bindings", [])

        occupations: list[str] = []
        nationalities: list[str] = []
        employers: list[str] = []
        awards: list[str] = []

        for row in bindings:
            if "occupationLabel" in row:
                val = row["occupationLabel"]["value"]
                if val not in occupations:
                    occupations.append(val)
            if "nationalityLabel" in row:
                val = row["nationalityLabel"]["value"]
                if val not in nationalities:
                    nationalities.append(val)
            if "employerLabel" in row:
                val = row["employerLabel"]["value"]
                if val not in employers:
                    employers.append(val)
            if "awardLabel" in row:
                val = row["awardLabel"]["value"]
                if val not in awards:
                    awards.append(val)

        signals = [
            Signal(key="wikidata_occupation", value=occupations, unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="wikidata_nationality",
                   value=nationalities[0] if nationalities else None,
                   unit=None, confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="wikidata_employer",
                   value=employers[0] if employers else None,
                   unit=None, confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="wikidata_awards", value=awards, unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
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
