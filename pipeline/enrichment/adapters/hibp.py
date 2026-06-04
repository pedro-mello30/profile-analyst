"""Have I Been Pwned breach-check adapter (Tier: medium, priority: 30)."""
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

_HIBP_BASE = "https://haveibeenpwned.com/api/v3"


class HibpAdapter(EnrichmentAdapter):
    """Have I Been Pwned breach-check adapter.

    Requires HIBP_API_KEY. Without it, returns immediately with no data.
    """

    adapter_id      = "hibp"
    display_name    = "Have I Been Pwned — breach check"
    requires        = ["email"]
    produces        = []
    tier            = "medium"
    priority        = 30
    cost_usd        = 0.004
    timeout_s       = 10
    retry_max       = 2
    rate_limit_rpm  = 10
    ttl_hours       = 168
    min_confidence  = 0.7
    max_instances   = 3
    osint_risk      = True
    secrets_required = ["HIBP_API_KEY"]
    gdpr_basis      = "LEGITIMATE_INTERESTS"
    data_category   = "OSINT"
    tos_compliant   = True
    robots_txt_policy = "RESPECT"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        api_key = config.secrets.get("HIBP_API_KEY", "")
        if not api_key:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="HIBP_API_KEY not configured", cached=False, ran_at=now,
                cost_usd=0.0, duration_s=time.monotonic() - t0,
            )

        email = seed_entities[0].value

        try:
            resp = requests.get(
                f"{_HIBP_BASE}/breachedaccount/{email}",
                params={"truncateResponse": "false"},
                headers={
                    "hibp-api-key": api_key,
                    "User-Agent": "profile-analyst/0.1",
                },
                timeout=self.timeout_s,
            )
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # HTTP 404 = no breaches found — this is success
        if resp.status_code == 404:
            signals: list[Signal] = [
                Signal(
                    key="hibp_api_authenticated",
                    value=True,
                    unit=None,
                    confidence=1.0,
                    method="config",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
                Signal(
                    key="hibp_breach_count",
                    value=0,
                    unit="count",
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
                Signal(
                    key="hibp_breach_names",
                    value=[],
                    unit=None,
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=True,
                ),
                Signal(
                    key="hibp_earliest_breach_year",
                    value=None,
                    unit=None,
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
                Signal(
                    key="hibp_latest_breach_year",
                    value=None,
                    unit=None,
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
            ]
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=signals,
                error=None, cached=False, ran_at=now, cost_usd=self.cost_usd,
                duration_s=time.monotonic() - t0,
            )

        if not resp.ok:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"HIBP HTTP {resp.status_code}: {resp.text[:200]}",
                cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        try:
            breaches: list[dict] = resp.json()
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"JSON parse error: {exc}", cached=False, ran_at=now,
                cost_usd=0.0, duration_s=time.monotonic() - t0,
            )

        breach_names: list[str] = []
        years: list[int] = []

        for breach in breaches:
            name = breach.get("Name") or breach.get("name")
            if name:
                breach_names.append(str(name))
            date_str = breach.get("BreachDate") or breach.get("breach_date") or ""
            if date_str:
                try:
                    year = int(str(date_str)[:4])
                    years.append(year)
                except (ValueError, TypeError):
                    pass

        earliest_year: int | None = min(years) if years else None
        latest_year: int | None = max(years) if years else None

        signals = [
            Signal(
                key="hibp_api_authenticated",
                value=True,
                unit=None,
                confidence=1.0,
                method="config",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="hibp_breach_count",
                value=len(breaches),
                unit="count",
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="hibp_breach_names",
                value=breach_names,
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=True,
            ),
            Signal(
                key="hibp_earliest_breach_year",
                value=earliest_year,
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="hibp_latest_breach_year",
                value=latest_year,
                unit=None,
                confidence=1.0,
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
            cost_usd=self.cost_usd,
            duration_s=time.monotonic() - t0,
        )
