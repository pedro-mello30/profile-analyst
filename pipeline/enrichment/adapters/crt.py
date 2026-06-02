"""crt.sh certificate-transparency adapter (Tier 0, seed)."""
from __future__ import annotations

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


class CrtAdapter(EnrichmentAdapter):
    adapter_id     = "crt"
    display_name   = "crt.sh Certificate Transparency"
    requires       = ["domain"]
    produces       = ["subdomain"]
    tier           = "seed"
    priority       = 10
    cost_usd       = 0.0
    timeout_s      = 10
    retry_max      = 1
    rate_limit_rpm = 0
    ttl_hours      = 168
    min_confidence = 0.7
    max_instances  = 3
    osint_risk     = False
    secrets_required = []
    gdpr_basis     = "LEGITIMATE_INTERESTS"
    data_category  = "OPEN_DATA"
    tos_compliant  = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0  = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        domain = seed_entities[0].value
        depth  = seed_entities[0].depth + 1

        try:
            resp = requests.get(
                f"https://crt.sh/?q=%.{domain}&output=json",
                timeout=self.timeout_s,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            records: list[dict] = resp.json()
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # ── Extract unique subdomains ──────────────────────────────────────────
        wildcard_prefix = f"*.{domain}"
        unique_subs: set[str] = set()

        for record in records:
            name_value = record.get("name_value", "")
            # name_value may contain multiple names separated by newlines
            for name in name_value.split("\n"):
                name = name.strip().lower()
                # Keep only entries that look like subdomains of our domain
                if name.endswith(f".{domain}") and name != wildcard_prefix:
                    unique_subs.add(name)

        # ── Build entities ─────────────────────────────────────────────────────
        entities: list[Entity] = []
        for sub in sorted(unique_subs):
            try:
                ent = make_entity(
                    "subdomain", sub,
                    source="crt", confidence=0.85, depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
            except Exception:
                pass

        signals: list[Signal] = [
            Signal(
                key="cert_count",
                value=len(records),
                unit="count",
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="subdomains_found",
                value=sorted(unique_subs),
                unit=None,
                confidence=0.85,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=entities,
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
            duration_s=time.monotonic() - t0,
        )
