"""Maigret username OSINT adapter (Tier: slow, priority: 50)."""
from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity, make_entity

# Map URL hostname patterns to entity types
# Order matters: more-specific patterns first
_URL_ENTITY_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"youtube\.com",      re.IGNORECASE), "youtube_handle"),
    (re.compile(r"github\.com",       re.IGNORECASE), "github_handle"),
    (re.compile(r"tiktok\.com",       re.IGNORECASE), "tiktok_handle"),
    (re.compile(r"twitter\.com",      re.IGNORECASE), "twitter_handle"),
    (re.compile(r"x\.com",            re.IGNORECASE), "twitter_handle"),
    (re.compile(r"twitch\.tv",        re.IGNORECASE), "twitch_handle"),
    (re.compile(r"reddit\.com",       re.IGNORECASE), "reddit_username"),
    (re.compile(r"[a-z0-9-]+\.substack\.com", re.IGNORECASE), "substack_url"),
    (re.compile(r"instagram\.com",    re.IGNORECASE), "instagram_handle"),
]

# Regex to extract handle/username from common URL patterns
_YOUTUBE_HANDLE_RE  = re.compile(r"youtube\.com/@([a-zA-Z0-9._-]{3,30})")
_YOUTUBE_CHANNEL_RE = re.compile(r"youtube\.com/(?:channel/|c/)([a-zA-Z0-9._-]+)")
_GITHUB_RE          = re.compile(r"github\.com/([a-zA-Z0-9-]{1,39})(?:/|$)")
_TIKTOK_RE          = re.compile(r"tiktok\.com/@([a-zA-Z0-9._]{1,24})")
_TWITTER_RE         = re.compile(r"(?:twitter|x)\.com/([a-zA-Z0-9_]{1,15})(?:/|$)")
_TWITCH_RE          = re.compile(r"twitch\.tv/([a-z0-9_]{4,25})(?:/|$)")
_REDDIT_RE          = re.compile(r"reddit\.com/u(?:ser)?/([a-zA-Z0-9_-]{3,20})")
_SUBSTACK_RE        = re.compile(r"(https?://[a-z0-9-]+\.substack\.com)(?:/|$)", re.IGNORECASE)
_INSTAGRAM_RE       = re.compile(r"instagram\.com/([a-z0-9._]{1,30})(?:/|$)", re.IGNORECASE)


def _extract_handle_from_url(url: str, entity_type: str) -> str | None:
    """Extract the normalized handle/value from a URL for the given entity type."""
    try:
        if entity_type == "youtube_handle":
            m = _YOUTUBE_HANDLE_RE.search(url)
            return f"@{m.group(1)}" if m else None
        if entity_type == "github_handle":
            m = _GITHUB_RE.search(url)
            return m.group(1) if m else None
        if entity_type == "tiktok_handle":
            m = _TIKTOK_RE.search(url)
            return f"@{m.group(1)}" if m else None
        if entity_type == "twitter_handle":
            m = _TWITTER_RE.search(url)
            return f"@{m.group(1)}" if m else None
        if entity_type == "twitch_handle":
            m = _TWITCH_RE.search(url)
            return m.group(1) if m else None
        if entity_type == "reddit_username":
            m = _REDDIT_RE.search(url)
            return m.group(1) if m else None
        if entity_type == "substack_url":
            m = _SUBSTACK_RE.search(url)
            if m:
                raw = m.group(1).rstrip("/")
                return raw if raw.startswith("https://") else f"https://{raw}"
            return None
        if entity_type == "instagram_handle":
            m = _INSTAGRAM_RE.search(url)
            return m.group(1) if m else None
    except Exception:
        pass
    return None


def _entity_type_for_url(url: str) -> str | None:
    """Return the best-matching entity type for a URL, or None."""
    for pattern, entity_type in _URL_ENTITY_MAP:
        if pattern.search(url):
            return entity_type
    return None


class MaigretAdapter(EnrichmentAdapter):
    """Maigret username OSINT adapter. Runs the maigret CLI; no API key required."""

    adapter_id      = "maigret"
    display_name    = "Maigret — username OSINT"
    requires        = ["handle"]
    produces        = [
        "youtube_handle", "tiktok_handle", "twitter_handle",
        "github_handle", "reddit_username", "twitch_handle",
        "substack_url", "instagram_handle",
    ]
    tier            = "slow"
    priority        = 50
    cost_usd        = 0.0
    timeout_s       = 310
    retry_max       = 1
    rate_limit_rpm  = 0
    ttl_hours       = 168
    min_confidence  = 0.8
    max_instances   = 1
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
        handle = seed.value
        depth = seed.depth + 1

        run_uuid = uuid.uuid4().hex[:8]
        json_output_path = Path(f"/tmp/maigret_{handle}_{run_uuid}.json")

        # Run maigret CLI
        try:
            proc = subprocess.run(
                [
                    "python3", "-m", "maigret",
                    handle,
                    "--timeout", "60",
                    "--retries", "1",
                    "--json", str(json_output_path),
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            cli_output = proc.stdout + proc.stderr
        except FileNotFoundError:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="maigret not installed", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )
        except subprocess.TimeoutExpired:
            cli_output = ""
        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Check for module not found
        if "No module named maigret" in cli_output or "No module named 'maigret'" in cli_output:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="maigret not installed", cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Read JSON output file
        raw_data: dict = {}
        try:
            if json_output_path.exists():
                raw_data = json.loads(json_output_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        finally:
            # Clean up temp file
            try:
                json_output_path.unlink(missing_ok=True)
            except Exception:
                pass

        entities: list[Entity] = []
        _entity_signals: list[Signal] = []
        platform_hits: list[dict] = []
        discovered_handles: list[str] = []
        sites_checked = 0

        # Maigret JSON structure: {"sites": {"SiteName": {"status": {...}, "url": "...", ...}, ...}}
        sites_data: dict = raw_data.get("sites", {})
        if not isinstance(sites_data, dict):
            sites_data = {}

        sites_checked = len(sites_data)

        seen_entity_pairs: set[tuple[str, str]] = set()

        for site_name, site_info in sites_data.items():
            if not isinstance(site_info, dict):
                continue

            # Determine status — maigret uses nested or flat status
            status_obj = site_info.get("status", {})
            if isinstance(status_obj, dict):
                status_str = status_obj.get("status", "") or ""
            else:
                status_str = str(status_obj)

            # Only process "Claimed" hits
            if "Claimed" not in status_str:
                continue

            url = site_info.get("url") or site_info.get("url_main") or ""
            if not url:
                continue

            platform_hits.append({"site": site_name, "url": url})

            entity_type = _entity_type_for_url(url)
            if entity_type is None:
                continue

            raw_value = _extract_handle_from_url(url, entity_type)
            if raw_value is None:
                continue

            # Track discovered alternate handles
            if entity_type in ("youtube_handle", "tiktok_handle", "twitter_handle",
                               "github_handle", "reddit_username", "twitch_handle",
                               "instagram_handle"):
                alt = raw_value.lstrip("@")
                if alt.lower() != handle.lower() and alt not in discovered_handles:
                    discovered_handles.append(alt)

            # De-duplicate entities
            pair = (entity_type, raw_value)
            if pair in seen_entity_pairs:
                continue
            seen_entity_pairs.add(pair)

            try:
                ent = make_entity(
                    entity_type, raw_value,
                    source="maigret", confidence=0.85, depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
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
                key="maigret_site_count",
                value=sites_checked,
                unit="count",
                confidence=1.0,
                method="osint",
                source=self.adapter_id,
                osint_risk=False,
            ),
            Signal(
                key="maigret_platform_hits",
                value=platform_hits,
                unit=None,
                confidence=0.9,
                method="osint",
                source=self.adapter_id,
                osint_risk=True,
            ),
            Signal(
                key="maigret_discovered_handles",
                value=discovered_handles,
                unit=None,
                confidence=0.85,
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
