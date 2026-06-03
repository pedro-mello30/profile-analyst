"""InstagramBioAdapter — extract identity entities from Instagram bio text (spec 0017 §5)."""
from __future__ import annotations

from datetime import datetime, timezone

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity, make_entity
from pipeline.enrichment.extractors.bio import BioEntityExtractor


class InstagramBioAdapter(EnrichmentAdapter):
    adapter_id       = "instagram_bio"
    display_name     = "Instagram Bio Entity Extractor"
    requires         = ["handle"]
    produces         = ["email", "phone", "cnpj", "website_url", "domain"]
    tier             = "seed"
    priority         = 0
    cost_usd         = 0.0
    timeout_s        = 5
    retry_max        = 0
    rate_limit_rpm   = 0
    ttl_hours        = 168
    min_confidence   = 0.5
    max_instances    = 1
    osint_risk       = True
    secrets_required = []
    gdpr_basis       = "LEGITIMATE_INTERESTS"
    data_category    = "PUBLIC_SCRAPE"
    tos_compliant    = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Guard clauses — return empty result, no error
        if config.dry_run:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )
        if config.context is None:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )
        if config.context.raw_profile is None:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
            )

        # Extract bio text and optional website from raw_profile
        bio = config.context.raw_profile.get("bio") or ""
        website = config.context.raw_profile.get("website")

        # Determine depth
        depth = (seed_entities[0].depth + 1) if seed_entities else 1

        # Delegate to BioEntityExtractor
        hits = BioEntityExtractor().extract(bio, website=website)

        # Build entity list, skipping any that fail validation
        entities: list[Entity] = []
        for entity_type, raw_value, confidence in hits:
            try:
                ent = make_entity(
                    entity_type, raw_value,
                    source=self.adapter_id,
                    confidence=confidence,
                    depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
            except Exception:
                pass  # Skip validation errors

        # Deduplicate by (type, value) — keep first occurrence
        seen: set[tuple[str, str]] = set()
        deduped: list[Entity] = []
        for ent in entities:
            key = (ent.type, ent.value)
            if key not in seen:
                seen.add(key)
                deduped.append(ent)

        signals = [
            Signal(
                key="bio_entity_count",
                value=len(deduped),
                unit="count",
                confidence=1.0,
                method="computed",
                source=self.adapter_id,
                osint_risk=False,
            ),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=deduped,
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
        )
