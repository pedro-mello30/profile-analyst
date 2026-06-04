"""GitHub enricher — extracts identity entities from GitHub API user response."""
from __future__ import annotations

from pipeline.enrichment.enrichers.base import EnrichmentEnricher


class GithubEnricher(EnrichmentEnricher):
    """GitHub enricher — extracts identity entities from GitHub API user response.

    Currently GitHub adapter produces signals (not entities), so extract() is a stub
    that returns an empty list.  Reserved for future use when entity extraction is added.
    """

    enricher_id = "github"
    adapter_id = "github"
    min_confidence = 0.5

    def extract(self, raw_data: dict) -> list:
        """Return empty list — GitHub produces signals, not entities, in the current pipeline."""
        return []
