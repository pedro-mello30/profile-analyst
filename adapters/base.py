"""SourceAdapter ABC — the source-agnostic ingestion + governance contract (spec §3).

Every data source must declare its governance posture as class attributes before any
data enters the pipeline. The ToS-flag gate (pipeline.compliance.tos) reads these.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SourceAdapter(ABC):
    """Abstract base for all data sources.

    Concrete adapters set the governance attributes below as class attributes and
    implement ``fetch_profile`` / ``fetch_media``.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    source_id: str = "abstract"
    # "OFFICIAL_API" | "CONSENT_BASED" | "PUBLIC_SCRAPE" | "DATA_BROKER" | "SAMPLE"
    data_category: str = "SAMPLE"
    tos_compliant: bool = False

    # ── Authentication ───────────────────────────────────────────────────────
    auth_type: str = "NONE"  # "NONE" | "OAUTH_USER" | "API_KEY" | "WEBHOOK"
    requires_creator_consent: bool = False

    # ── Rate limits ──────────────────────────────────────────────────────────
    calls_per_window: int = 0
    window_seconds: int = 3600

    # ── Field availability ───────────────────────────────────────────────────
    available_fields: set[str] = set()
    estimated_fields: set[str] = set()  # modeled/inferred, not first-party

    # ── Legal ────────────────────────────────────────────────────────────────
    gdpr_basis: str = "NONE"  # "CONSENT" | "LEGITIMATE_INTERESTS" | "CONTRACT" | "NONE"
    requires_lia: bool = False

    # ── Retention ────────────────────────────────────────────────────────────
    max_retention_days: int = 90
    deletion_on_request: bool = True

    @abstractmethod
    def fetch_profile(self, handle: str) -> dict:
        """Return the raw profile record for ``handle`` as a plain dict."""
        raise NotImplementedError

    @abstractmethod
    def fetch_media(self, handle: str, limit: int = 20) -> list[dict]:
        """Return up to ``limit`` raw media records for ``handle``, newest first."""
        raise NotImplementedError
