"""Press enricher — extracts press mention entities from GDELT response. Stub."""
from __future__ import annotations

from pipeline.enrichment.enrichers.base import EnrichmentEnricher


class PressEnricher(EnrichmentEnricher):
    """Press enricher — extracts press mention entities from GDELT response. Stub.

    GDELT produces signals (tone, coverage volume, etc.) rather than named entities
    in the current pipeline.  This enricher is reserved for future use.
    """

    enricher_id = "press"
    adapter_id = "gdelt"
    min_confidence = 0.6

    def extract(self, raw_data: dict) -> list:
        """Return empty list — GDELT produces signals, not entities, in the current pipeline."""
        return []
