"""RDAP/WHOIS enrichment adapter (Tier 0, seed) — terminal, produces no entities."""
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
from pipeline.enrichment.entity import Entity


class WhoisAdapter(EnrichmentAdapter):
    adapter_id     = "whois"
    display_name   = "RDAP / WHOIS"
    requires       = ["domain"]
    produces       = []          # terminal — signals only
    tier           = "seed"
    priority       = 5
    cost_usd       = 0.0
    timeout_s      = 10
    retry_max      = 1
    rate_limit_rpm = 0
    ttl_hours      = 168
    min_confidence = 0.8
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

        try:
            resp = requests.get(
                f"https://rdap.org/domain/{domain}",
                timeout=self.timeout_s,
                headers={"Accept": "application/rdap+json,application/json"},
            )
            resp.raise_for_status()
            data: dict = resp.json()
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # ── Registrar ─────────────────────────────────────────────────────────
        registrar = data.get("handle") or "unknown"

        # ── Registration date ─────────────────────────────────────────────────
        reg_date_str: str | None = None
        domain_age_days: int | None = None
        for event in data.get("events", []):
            if event.get("eventAction") == "registration":
                reg_date_str = event.get("eventDate")
                break

        if reg_date_str:
            try:
                reg_dt = datetime.fromisoformat(reg_date_str.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                domain_age_days = (now_dt - reg_dt).days
                # Normalise to bare ISO date (YYYY-MM-DD)
                reg_date_str = reg_dt.date().isoformat()
            except Exception:
                reg_date_str = None
                domain_age_days = None

        signals: list[Signal] = [
            Signal(
                key="domain_registrar",
                value=registrar,
                unit=None,
                confidence=0.9,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
        ]

        if domain_age_days is not None:
            signals.append(Signal(
                key="domain_age_days",
                value=domain_age_days,
                unit="days",
                confidence=0.9,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ))

        if reg_date_str:
            signals.append(Signal(
                key="domain_creation_date",
                value=reg_date_str,
                unit=None,
                confidence=0.9,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ))

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
