"""ToS compliance gate + governance block builder (spec §3, §9.4)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adapters.base import SourceAdapter

REQUIRED_GOVERNANCE_FIELDS = {
    "source_id",
    "data_category",
    "tos_compliant_at_ingest",
    "ingested_at",
    "gdpr_basis",
    "subject_jurisdiction",
    "retention_expires_at",
    "consent_record_id",
}


class TosComplianceError(Exception):
    def __init__(self, source_id: str, data_category: str) -> None:
        self.source_id = source_id
        self.data_category = data_category
        super().__init__(
            f"Source '{source_id}' (category={data_category}) is not ToS-compliant. "
            "Set ALLOW_NONCOMPLIANT=true to override (test/dev only)."
        )


class ComplianceError(Exception):
    pass


def allow_noncompliant() -> bool:
    """Returns True only when ALLOW_NONCOMPLIANT is exactly the string 'true'."""
    return os.environ.get("ALLOW_NONCOMPLIANT", "") == "true"


def enforce_tos_gate(adapter: "SourceAdapter") -> None:
    """Raise TosComplianceError if adapter is non-compliant and override is not set."""
    if not adapter.tos_compliant and not allow_noncompliant():
        raise TosComplianceError(adapter.source_id, adapter.data_category)


def build_governance_block(
    adapter: "SourceAdapter",
    *,
    subject_jurisdiction: str,
    ingested_at: datetime,
    consent_record_id: str | None = None,
) -> dict:
    """Build the full 8-field governance block to embed in Stage 1 output."""
    retention_expires_at = ingested_at + timedelta(days=adapter.max_retention_days)
    return {
        "source_id": adapter.source_id,
        "data_category": adapter.data_category,
        "tos_compliant_at_ingest": adapter.tos_compliant,
        "ingested_at": ingested_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gdpr_basis": adapter.gdpr_basis,
        "subject_jurisdiction": subject_jurisdiction,
        "retention_expires_at": retention_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "consent_record_id": consent_record_id,
    }


def assert_governance_complete(gov: dict) -> None:
    """Raise ComplianceError if any required governance field is missing."""
    missing = REQUIRED_GOVERNANCE_FIELDS - set(gov.keys())
    if missing:
        raise ComplianceError(
            f"Governance block is incomplete. Missing fields: {sorted(missing)}"
        )


class UilLiaError(ComplianceError):
    """Raised when Stage 4 UIL is invoked without a Legitimate Interest Assessment on file."""

    def __init__(self, handle: str) -> None:
        self.handle = handle
        super().__init__(
            f"Stage 4 UIL requires a Legitimate Interest Assessment (LIA) for handle "
            f"'{handle}'. Set LIA_FILE_PATH env var to the LIA document path."
        )


def uil_lia_gate(handle: str) -> None:
    """Raise UilLiaError if no LIA file is configured for UIL on ``handle``.

    Reads the ``LIA_FILE_PATH`` environment variable. Missing or empty → raises.
    This gate fires at Stage 4 entry before any data is fetched.
    """
    lia_path = os.environ.get("LIA_FILE_PATH", "").strip()
    if not lia_path:
        raise UilLiaError(handle)
