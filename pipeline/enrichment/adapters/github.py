"""GitHub public profile adapter (fast tier, priority 30)."""
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


class GitHubAdapter(EnrichmentAdapter):
    """GitHub public profile adapter. Unauthenticated requests are subject to 60 req/hr per IP."""

    adapter_id       = "github"
    display_name     = "GitHub Public Profile"
    requires         = ["github_handle"]
    produces         = []
    tier             = "fast"
    priority         = 30
    cost_usd         = 0.0
    timeout_s        = 10
    retry_max        = 1
    rate_limit_rpm   = 0
    ttl_hours        = 24
    min_confidence   = 0.5
    max_instances    = 1
    osint_risk       = False
    secrets_required = []
    gdpr_basis       = "LEGITIMATE_INTERESTS"
    data_category    = "PUBLIC_API"
    tos_compliant    = True
    robots_txt_policy = "N/A"

    _HEADERS = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-analyst/0.1",
    }

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0  = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        handle = seed_entities[0].value

        try:
            resp = requests.get(
                f"https://api.github.com/users/{handle}",
                headers=self._HEADERS,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        signals: list[Signal] = [
            Signal(
                key="github_public_repos",
                value=data.get("public_repos", 0),
                unit="count",
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="github_followers",
                value=data.get("followers", 0),
                unit="count",
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="github_bio",
                value=data.get("bio") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="github_company",
                value=data.get("company") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="github_location",
                value=data.get("location") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="github_created_at",
                value=data.get("created_at") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="github_top_languages",
                value=[],
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
            cost_usd=0.0,
            duration_s=time.monotonic() - t0,
        )
