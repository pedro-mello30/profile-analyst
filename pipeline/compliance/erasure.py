"""GDPR Art.17 erasure helpers + retention enforcement (spec §9.1)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline.compliance.tos import ComplianceError


@dataclass
class ErasureReceipt:
    handle: str
    erased_at: str
    artifacts_deleted: list[str]
    bytes_freed: int
    existed: bool


def _safe_handle(handle: str) -> str:
    """Reject path-traversal attempts; return handle unchanged if safe."""
    if not handle or "/" in handle or handle.startswith(".") or Path(handle).is_absolute():
        raise ComplianceError(
            f"Unsafe handle '{handle}': handle must be a plain directory name with "
            "no slashes, leading dots, or absolute paths."
        )
    return handle


def erase_profile(
    handle: str,
    *,
    dry_run: bool = False,
    projects_root: Path | str = "projects",
) -> ErasureReceipt:
    """Delete all artifacts for ``handle`` under ``projects_root``.

    Idempotent — returns a receipt with existed=False when nothing to delete.
    Path-traversal guard applied before any filesystem operation.
    """
    _safe_handle(handle)
    root = Path(projects_root)
    profile_dir = root / handle
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not profile_dir.exists():
        return ErasureReceipt(
            handle=handle,
            erased_at=now_iso,
            artifacts_deleted=[],
            bytes_freed=0,
            existed=False,
        )

    # Enumerate before deleting
    artifacts: list[str] = []
    bytes_freed = 0
    for path in profile_dir.rglob("*"):
        if path.is_file():
            artifacts.append(str(path.relative_to(root)))
            bytes_freed += path.stat().st_size

    if not dry_run:
        shutil.rmtree(profile_dir)

    return ErasureReceipt(
        handle=handle,
        erased_at=now_iso,
        artifacts_deleted=artifacts,
        bytes_freed=bytes_freed,
        existed=True,
    )


def is_expired(retention_expires_at: str, *, now: datetime | None = None) -> bool:
    """Return True if retention_expires_at is in the past."""
    if now is None:
        now = datetime.now(timezone.utc)
    expiry = datetime.fromisoformat(retention_expires_at.replace("Z", "+00:00"))
    return now >= expiry


def assert_within_retention(
    governance: dict,
    *,
    handle: str,
    auto_erase: bool = False,
) -> None:
    """Raise ComplianceError (or auto-erase) if retention window has expired."""
    expires_at = governance.get("retention_expires_at")
    if expires_at and is_expired(expires_at):
        if auto_erase:
            erase_profile(handle)
        raise ComplianceError(
            f"Profile '{handle}' retention expired at {expires_at}. "
            "Erase and re-ingest to continue processing."
        )


def gc_sweep(projects_root: Path | str = "projects") -> list[ErasureReceipt]:
    """Walk projects/*/02-normalized.json, erase any profile past its retention window."""
    root = Path(projects_root)
    receipts: list[ErasureReceipt] = []
    if not root.exists():
        return receipts

    import json  # local import to avoid top-level dep

    for norm_file in root.glob("*/02-normalized.json"):
        handle = norm_file.parent.name
        try:
            with open(norm_file) as fh:
                doc = json.load(fh)
            gov = doc.get("governance", {})
            expires_at = gov.get("retention_expires_at")
            if expires_at and is_expired(expires_at):
                receipt = erase_profile(handle, projects_root=root)
                receipts.append(receipt)
        except Exception:
            continue

    return receipts
