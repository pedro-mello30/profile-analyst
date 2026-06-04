"""Enrichers package — pure data-transformation layer (spec-0019 §5.3)."""
from pipeline.enrichment.enrichers.base import EnrichmentEnricher, EnricherContractError

__all__ = ["EnrichmentEnricher", "EnricherContractError"]
