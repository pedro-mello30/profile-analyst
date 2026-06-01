"""SampleUILAdapter — reads a local cross_platform.json fixture (spec 0011 §3, T7)."""
from __future__ import annotations

import json
from pathlib import Path

from adapters.cross_platform.base import CrossPlatformAdapter


class SampleUILAdapter(CrossPlatformAdapter):
    source_id = "sample_uil"
    data_category = "public_profile"
    tos_compliant = True
    auth_type = "NONE"
    requires_creator_consent = True
    calls_per_window = 1000
    window_seconds = 3600
    available_fields = {
        "platform", "candidate_handle", "display_name", "bio",
        "website", "profile_photo_url",
    }
    estimated_fields: set[str] = set()
    gdpr_basis = "LEGITIMATE_INTERESTS"
    requires_lia = True
    max_retention_days = 90
    deletion_on_request = True

    def __init__(self, projects_root: Path | str | None = None) -> None:
        if projects_root is None:
            projects_root = Path(__file__).parent.parent.parent / "projects"
        self._projects_root = Path(projects_root)

    def _fixture_path(self, handle: str) -> Path:
        return self._projects_root / handle / "00-input" / "cross_platform.json"

    def fetch_candidates(self, handle: str) -> list[dict]:
        """Load candidate accounts from the local fixture (no network)."""
        path = self._fixture_path(handle)
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        return data.get("candidates", [])
