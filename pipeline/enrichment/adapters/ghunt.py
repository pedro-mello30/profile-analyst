"""GHunt Google account OSINT adapter (Tier: medium, priority: 25)."""
from __future__ import annotations

import json
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


class GhuntAdapter(EnrichmentAdapter):
    """GHunt Google account OSINT adapter.

    Requires GHUNT_COOKIES (exported via `ghunt login`). Returns immediately without them.
    """

    adapter_id      = "ghunt"
    display_name    = "GHunt — Google account OSINT"
    requires        = ["gmail"]
    produces        = ["youtube_channel_id"]
    tier            = "medium"
    priority        = 25
    cost_usd        = 0.0
    timeout_s       = 60
    retry_max       = 1
    rate_limit_rpm  = 0
    ttl_hours       = 72
    min_confidence  = 0.7
    max_instances   = 1
    osint_risk      = True
    secrets_required = ["GHUNT_COOKIES"]
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

        # Require GHUNT_COOKIES secret
        if not config.secrets.get("GHUNT_COOKIES", ""):
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="GHUNT_COOKIES not configured", cached=False, ran_at=now,
                cost_usd=0.0, duration_s=time.monotonic() - t0,
            )

        seed = seed_entities[0]
        gmail = seed.value
        depth = seed.depth + 1

        # Run ghunt CLI
        try:
            proc = subprocess.run(
                ["python3", "-m", "ghunt", "email", gmail, "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            output = proc.stdout + proc.stderr
        except FileNotFoundError:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="ghunt not installed", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="ghunt timed out", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Check for module not found
        if "No module named ghunt" in output or "No module named 'ghunt'" in output:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="ghunt not installed", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Parse JSON output — ghunt emits JSON to stdout
        data: dict = {}
        try:
            # Find the JSON portion of the output (ghunt may print status lines first)
            for i, line in enumerate(output.splitlines()):
                stripped = line.strip()
                if stripped.startswith("{"):
                    data = json.loads("\n".join(output.splitlines()[i:]))
                    break
        except (json.JSONDecodeError, ValueError):
            pass

        entities: list[Entity] = []
        _entity_signals: list[Signal] = []
        youtube_found = False
        maps_review_count = 0
        workspace_name: str | None = None

        if data:
            # Extract YouTube channels
            channels = data.get("youtube", {}).get("channels", [])
            if not isinstance(channels, list):
                channels = []
            for channel in channels:
                channel_id = channel.get("id") or channel.get("channel_id") or ""
                if channel_id and channel_id.startswith("UC"):
                    try:
                        ent = make_entity(
                            "youtube_channel_id", channel_id,
                            source="ghunt", confidence=0.9, depth=depth,
                            discovered_at=now,
                        )
                        entities.append(ent)
                        youtube_found = True
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

            # Maps review count
            try:
                maps_review_count = int(
                    data.get("maps", {}).get("review_count", 0) or 0
                )
            except (TypeError, ValueError):
                maps_review_count = 0

            # Workspace / organization name
            workspace_name = (
                data.get("workspace", {}).get("name")
                or data.get("organization", {}).get("name")
                or None
            )
            if workspace_name is not None:
                workspace_name = str(workspace_name).strip() or None

        signals: list[Signal] = [
            *_entity_signals,
            Signal(
                key="ghunt_cookies_configured",
                value=True,
                unit=None,
                confidence=1.0,
                method="config",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="ghunt_youtube_found",
                value=youtube_found,
                unit=None,
                confidence=0.9,
                method="osint",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="ghunt_maps_review_count",
                value=maps_review_count,
                unit="count",
                confidence=0.8,
                method="osint",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="ghunt_workspace_name",
                value=workspace_name,
                unit=None,
                confidence=0.8,
                method="osint",
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
