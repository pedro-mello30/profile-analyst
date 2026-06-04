"""Holehe email-to-service OSINT adapter (Tier: medium, priority: 20)."""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity, make_entity


class HoleheAdapter(EnrichmentAdapter):
    """Holehe email-to-service OSINT adapter. Runs the holehe CLI; no API key required."""

    adapter_id      = "holehe"
    display_name    = "Holehe — email to service OSINT"
    requires        = ["email"]
    produces        = ["gmail"]
    tier            = "medium"
    priority        = 20
    cost_usd        = 0.0
    timeout_s       = 60
    retry_max       = 1
    rate_limit_rpm  = 30
    ttl_hours       = 72
    min_confidence  = 0.7
    max_instances   = 2
    osint_risk      = True
    secrets_required = []
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

        seed = seed_entities[0]
        email = seed.value
        depth = seed.depth + 1

        # Run holehe CLI
        try:
            proc = subprocess.run(
                ["python3", "-m", "holehe", email, "--only-used", "--no-color"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            output = proc.stdout + proc.stderr
        except FileNotFoundError:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="holehe not installed", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="holehe timed out", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Check for "module not found" style error
        if "No module named holehe" in output or "No module named 'holehe'" in output:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="holehe not installed", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Parse output: lines with "[+]" or "✔" indicate registered services
        services: list[str] = []
        for line in output.splitlines():
            if "[+]" in line or "✔" in line:
                # Extract service name — typically the first word after the marker
                stripped = line.strip()
                # Remove leading marker characters
                for marker in ("[+]", "✔"):
                    stripped = stripped.replace(marker, "").strip()
                # Service name is the first token
                parts = stripped.split()
                if parts:
                    services.append(parts[0])

        entities: list[Entity] = []
        _entity_signals: list[Signal] = []

        # If email ends with @gmail.com, produce a gmail entity
        if email.endswith("@gmail.com"):
            try:
                gmail_ent = make_entity(
                    "gmail", email,
                    source="holehe", confidence=0.95, depth=depth,
                    discovered_at=now,
                )
                entities.append(gmail_ent)
            except ValueError:
                pass
            except Exception as e:
                _entity_signals.append(Signal(
                    key="entity_creation_error",
                    value=str(e),
                    unit=None,
                    confidence=0.0,
                    method="internal",
                    source=self.adapter_id,
                    osint_risk=False,
                ))

        signals: list[Signal] = [
            *_entity_signals,
            Signal(
                key="holehe_service_count",
                value=len(services),
                unit="count",
                confidence=0.9,
                method="osint",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="holehe_services",
                value=services,
                unit=None,
                confidence=0.9,
                method="osint",
                source=self.adapter_id,
                osint_risk=True,
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
