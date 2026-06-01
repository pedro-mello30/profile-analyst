"""CrossPlatformAdapter ABC — governance contract for UIL candidate sources (spec 0011 §3)."""
from __future__ import annotations

from abc import abstractmethod

from adapters.base import SourceAdapter


class CrossPlatformAdapter(SourceAdapter):
    """Abstract base for cross-platform identity-linkage (UIL) candidate sources.

    Inherits the full SourceAdapter governance posture. Concrete adapters
    implement ``fetch_candidates`` instead of ``fetch_profile`` / ``fetch_media``.

    Architecture invariant: governance is declared as class attributes before any
    data enters the pipeline (governance-before-data).
    """

    requires_creator_consent: bool = True  # UIL candidates always require consent

    def fetch_profile(self, handle: str) -> dict:  # pragma: no cover
        raise NotImplementedError("Use fetch_candidates for cross-platform adapters")

    def fetch_media(self, handle: str, limit: int = 20) -> list[dict]:  # pragma: no cover
        raise NotImplementedError("Use fetch_candidates for cross-platform adapters")

    @abstractmethod
    def fetch_candidates(self, handle: str) -> list[dict]:
        """Return candidate account dicts for ``handle`` across target platforms.

        Each dict must include at minimum:
            platform, candidate_handle, display_name (nullable),
            bio (nullable), website (nullable), profile_photo_url (nullable)
        """
        raise NotImplementedError
