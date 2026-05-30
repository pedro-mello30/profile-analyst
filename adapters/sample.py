"""SampleAdapter — reads a local JSON fixture for offline/test use (spec §3)."""
from __future__ import annotations

import json
from pathlib import Path

from adapters.base import SourceAdapter


class SampleAdapter(SourceAdapter):
    source_id = "sample"
    data_category = "SAMPLE"
    tos_compliant = True
    auth_type = "NONE"
    requires_creator_consent = False
    calls_per_window = 1000
    window_seconds = 3600
    available_fields = {
        "handle", "display_name", "bio", "website", "is_verified", "is_business",
        "account_type", "followers", "following", "post_count", "snapshot_at",
        "media_id", "media_type", "posted_at", "likes", "comments", "saves",
        "shares", "views", "caption", "hashtags", "mentions",
        "is_paid_partnership", "paid_partner_handle",
    }
    estimated_fields: set[str] = set()
    gdpr_basis = "LEGITIMATE_INTERESTS"
    requires_lia = False
    max_retention_days = 90
    deletion_on_request = True

    def __init__(self, projects_root: Path | str | None = None) -> None:
        if projects_root is None:
            projects_root = Path(__file__).parent.parent / "projects"
        self._projects_root = Path(projects_root)

    def _fixture_path(self, handle: str) -> Path:
        return self._projects_root / handle / "00-input" / "sample.json"

    def _load(self, handle: str) -> dict:
        path = self._fixture_path(handle)
        if not path.exists():
            raise FileNotFoundError(f"SampleAdapter: fixture not found at {path}")
        with open(path) as fh:
            return json.load(fh)

    def fetch_profile(self, handle: str) -> dict:
        data = self._load(handle)
        profile = {k: v for k, v in data.items() if k != "media"}
        profile.setdefault("handle", handle)
        return profile

    def fetch_media(self, handle: str, limit: int = 20) -> list[dict]:
        data = self._load(handle)
        return data.get("media", [])[:limit]
