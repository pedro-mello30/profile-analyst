"""Twitch public profile adapter via Helix API (fast tier, priority 40)."""
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


class TwitchAdapter(EnrichmentAdapter):
    adapter_id       = "twitch"
    display_name     = "Twitch Public Profile"
    requires         = ["twitch_handle", "handle"]
    produces         = []
    tier             = "fast"
    priority         = 40
    cost_usd         = 0.0
    timeout_s        = 10
    retry_max        = 1
    rate_limit_rpm   = 0
    ttl_hours        = 24
    min_confidence   = 0.5
    max_instances    = 1
    osint_risk       = False
    secrets_required = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"]
    gdpr_basis       = "LEGITIMATE_INTERESTS"
    data_category    = "PUBLIC_API"
    tos_compliant    = True

    def _get_token(self, client_id: str, client_secret: str) -> str:
        """Obtain a client-credentials OAuth token from Twitch."""
        resp = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "client_credentials",
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0  = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        client_id     = config.secrets.get("TWITCH_CLIENT_ID", "")
        client_secret = config.secrets.get("TWITCH_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="Twitch credentials not configured",
                cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Prefer twitch_handle entity; fall back to generic handle
        handle_entity = next(
            (e for e in seed_entities if e.type == "twitch_handle"), seed_entities[0]
        )
        handle = handle_entity.value

        try:
            token = self._get_token(client_id, client_secret)

            headers = {
                "Client-Id":     client_id,
                "Authorization": f"Bearer {token}",
            }

            # GET user info
            user_resp = requests.get(
                f"https://api.twitch.tv/helix/users?login={handle}",
                headers=headers,
                timeout=self.timeout_s,
            )
            user_resp.raise_for_status()
            user_data = user_resp.json().get("data", [])

            if not user_data:
                return AdapterResult(
                    adapter_id=self.adapter_id, entities=[], signals=[],
                    error=f"Twitch user not found: {handle!r}",
                    cached=False, ran_at=now, cost_usd=0.0,
                    duration_s=time.monotonic() - t0,
                )

            user          = user_data[0]
            user_id       = user["id"]
            broadcaster_type = user.get("broadcaster_type", "")
            created_at    = user.get("created_at", "")

            # GET follower count
            follower_resp = requests.get(
                f"https://api.twitch.tv/helix/channels/followers?broadcaster_id={user_id}",
                headers=headers,
                timeout=self.timeout_s,
            )
            follower_resp.raise_for_status()
            follower_count = follower_resp.json().get("total", 0)

        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        signals: list[Signal] = [
            Signal(
                key="twitch_follower_count",
                value=int(follower_count),
                unit="count",
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="twitch_broadcaster_type",
                value=broadcaster_type,
                unit=None,
                confidence=1.0,
                method="api",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="twitch_account_created_at",
                value=created_at,
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
