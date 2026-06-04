"""Spotify Web API adapter (spec 0014 — fast tier, priority 25)."""
from __future__ import annotations

import base64
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
from pipeline.enrichment.entity import Entity, make_entity

_SOURCE = "spotify"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_ARTISTS_URL = "https://api.spotify.com/v1/artists/{id}"
_SEARCH_URL = "https://api.spotify.com/v1/search"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_token(client_id: str, client_secret: str, timeout_s: int) -> str:
    """Fetch a client-credentials OAuth token. Raises on failure."""
    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode())
    return data["access_token"]


class SpotifyAdapter(EnrichmentAdapter):
    """Spotify Web API adapter.

    Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET. Returns immediately without them.
    """

    adapter_id = "spotify"
    display_name = "Spotify Web API"
    requires = ["spotify_artist_id", "podcast_url", "display_name"]
    produces = ["spotify_artist_id"]
    tier = "fast"
    priority = 25
    cost_usd = 0.0
    timeout_s = 15
    retry_max = 2
    rate_limit_rpm = 0
    ttl_hours = 72
    min_confidence = 0.5
    max_instances = 2
    osint_risk = False
    secrets_required = []
    gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_API"
    tos_compliant = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = _now()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        client_id = config.secrets.get("SPOTIFY_CLIENT_ID", "")
        client_secret = config.secrets.get("SPOTIFY_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="SPOTIFY_CLIENT_ID not configured",
                cached=False, ran_at=now, cost_usd=0.0,
            )

        # Obtain access token
        try:
            token = _get_token(client_id, client_secret, self.timeout_s)
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=f"token fetch failed: {exc}",
                cached=False, ran_at=now, cost_usd=0.0,
            )

        auth_header = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        artist_id_entity = next(
            (e for e in seed_entities if e.type == "spotify_artist_id"), None
        )
        display_name_entity = next(
            (e for e in seed_entities if e.type == "display_name"), None
        )

        item_data: dict | None = None
        item_type: str = "artist"

        if artist_id_entity is not None:
            # Strip "spotify:artist:" prefix to get the bare ID
            raw_id = artist_id_entity.value
            if raw_id.startswith("spotify:artist:"):
                bare_id = raw_id[len("spotify:artist:"):]
            else:
                bare_id = raw_id
            url = _ARTISTS_URL.format(id=bare_id)
            try:
                req = urllib.request.Request(url, headers=auth_header)
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    item_data = json.loads(resp.read().decode())
                item_type = item_data.get("type", "artist")
            except Exception as exc:
                return AdapterResult(
                    adapter_id=self.adapter_id, entities=[], signals=[],
                    error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                )
        elif display_name_entity is not None:
            # Search by name for artist or show
            name = display_name_entity.value
            params = urllib.parse.urlencode({
                "q": name,
                "type": "artist,show",
                "limit": "3",
            })
            url = _SEARCH_URL + "?" + params
            try:
                req = urllib.request.Request(url, headers=auth_header)
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    search_data = json.loads(resp.read().decode())
            except Exception as exc:
                return AdapterResult(
                    adapter_id=self.adapter_id, entities=[], signals=[],
                    error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                )

            # Prefer artists, fall back to shows
            artists = search_data.get("artists", {}).get("items", [])
            shows = search_data.get("shows", {}).get("items", [])
            if artists:
                item_data = artists[0]
                item_type = "artist"
            elif shows:
                item_data = shows[0]
                item_type = "show"
        else:
            # Only podcast_url available — no search term, nothing to do
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="no usable seed entity for Spotify search",
                cached=False, ran_at=now, cost_usd=0.0,
            )

        if item_data is None:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="no Spotify result found",
                cached=False, ran_at=now, cost_usd=0.0,
            )

        # ── Extract common fields ──────────────────────────────────────────
        followers = item_data.get("followers", {})
        follower_count: int | None
        if isinstance(followers, dict):
            follower_count = followers.get("total")
        else:
            follower_count = None

        genres: list[str] = item_data.get("genres", [])
        popularity: int | None = item_data.get("popularity")

        # ── Produce spotify_artist_id entity from search result ───────────
        entities: list[Entity] = []
        _entity_signals: list[Signal] = []
        if artist_id_entity is None and item_type == "artist":
            # We found an artist via search — produce the normalised entity
            spotify_id = item_data.get("id", "")
            if spotify_id:
                try:
                    depth = (display_name_entity.depth + 1)  # type: ignore[union-attr]
                    entity = make_entity(
                        "spotify_artist_id",
                        f"spotify:artist:{spotify_id}",
                        source=_SOURCE,
                        confidence=0.8,
                        depth=depth,
                        discovered_at=now,
                    )
                    entities.append(entity)
                except ValueError:
                    pass
                except Exception as e:
                    _entity_signals.append(Signal(
                        key="entity_creation_error",
                        value=str(e),
                        unit=None,
                        confidence=0.0,
                        method="internal",
                        source=_SOURCE,
                        osint_risk=False,
                    ))

        signals = [
            *_entity_signals,
            Signal(key="spotify_api_authenticated", value=True, unit=None,
                   confidence=1.0, method="config", source=_SOURCE, osint_risk=False),
            Signal(key="spotify_follower_count",
                   value=int(follower_count) if follower_count is not None else None,
                   unit="followers", confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="spotify_genres", value=genres, unit=None,
                   confidence=1.0, method="api", source=_SOURCE, osint_risk=False),
            Signal(key="spotify_popularity",
                   value=int(popularity) if popularity is not None else None,
                   unit="score_0_100", confidence=1.0, method="api",
                   source=_SOURCE, osint_risk=False),
            Signal(key="spotify_type", value=item_type, unit=None,
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
