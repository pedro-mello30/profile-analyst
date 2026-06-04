"""CNPJ company lookup adapter via BrasilAPI (fast tier, priority 45)."""
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


class CNPJAdapter(EnrichmentAdapter):
    """Brazilian CNPJ company-registry lookup via BrasilAPI. Public endpoint; no auth required."""

    adapter_id       = "cnpj"
    display_name     = "CNPJ Company Lookup (BrasilAPI)"
    requires         = ["cnpj"]
    produces         = []
    tier             = "fast"
    priority         = 45
    cost_usd         = 0.0
    timeout_s        = 10
    retry_max        = 1
    rate_limit_rpm   = 0
    ttl_hours        = 168
    min_confidence   = 0.5
    max_instances    = 1
    osint_risk       = True
    secrets_required = []
    gdpr_basis       = "LEGITIMATE_INTERESTS"
    data_category    = "OPEN_DATA"
    tos_compliant    = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0  = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        cnpj_entity = seed_entities[0]
        cnpj_digits = cnpj_entity.value  # already normalized to 14 digits by entity layer

        try:
            resp = requests.get(
                f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_digits}",
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

        # Extract partner names from qsa list
        partners: list[str] = [
            entry.get("nome_socio", "")
            for entry in (data.get("qsa") or [])
            if entry.get("nome_socio")
        ]

        signals: list[Signal] = [
            Signal(
                key="cnpj_legal_name",
                value=data.get("razao_social") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="cnpj_trade_name",
                value=data.get("nome_fantasia") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="cnpj_status",
                value=data.get("descricao_situacao_cadastral") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="cnpj_cnae_primary",
                value=data.get("cnae_fiscal_descricao") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="cnpj_open_date",
                value=data.get("data_inicio_atividade") or "",
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="cnpj_share_capital",
                value=float(data.get("capital_social") or 0),
                unit="BRL",
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="cnpj_partners",
                value=partners,
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=True,
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
