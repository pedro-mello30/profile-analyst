"""CrossPlatformEnricher — synthesizes platform-scope signals from full entity pool."""
from __future__ import annotations

from pipeline.enrichment.enrichers.base import EnrichmentEnricher


class CrossPlatformEnricher(EnrichmentEnricher):
    """CrossPlatformEnricher — synthesizes platform-scope signals from full entity pool.

    Runs post-loop (spec-0019 §5.3).  adapter_id=None is intentional: this enricher
    is not tied to a single upstream adapter but operates over the aggregated entity pool.
    """

    enricher_id = "cross_platform"
    adapter_id = None  # spec-0019 §5.3: intentionally None
    min_confidence = 0.5

    def extract(self, raw_data) -> list:
        """Return empty list — stub for future platform scoring across the entity pool."""
        return []
