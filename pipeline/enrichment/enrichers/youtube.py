"""YouTube enricher — extracts identity entities from YouTube API channel response."""
from __future__ import annotations

import logging

from pipeline.enrichment.enrichers.base import EnrichmentEnricher
from pipeline.enrichment.entity import make_entity

logger = logging.getLogger(__name__)


class YouTubeEnricher(EnrichmentEnricher):
    """Extracts youtube_channel_id entities from YouTube Data API v3 channel response."""

    enricher_id = "youtube"
    adapter_id = "youtube"
    min_confidence = 0.6

    def extract(self, raw_data: dict) -> list:
        """Extract entities from a YouTube API channel response dict.

        Expects the structure returned by channels.list with ``part=id,snippet,statistics``.
        Returns empty list if no items are present or if the channel id doesn't start with 'UC'.
        Never raises — partial/missing fields produce fewer entities.
        """
        items = raw_data.get("items") if isinstance(raw_data, dict) else None
        if not items:
            return []

        entities = []
        first_item = items[0]
        channel_id = first_item.get("id", "")
        if isinstance(channel_id, str) and channel_id.startswith("UC"):
            try:
                entity = make_entity(
                    "youtube_channel_id",
                    channel_id,
                    source=self.enricher_id,
                    confidence=self.min_confidence,
                    depth=1,
                )
                entities.append(entity)
            except Exception as exc:
                logger.debug("YouTubeEnricher: skipping channel_id %r: %s", channel_id, exc)

        return entities
