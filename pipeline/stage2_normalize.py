"""Stage 2 NORMALIZE — deserialize raw record into canonical Profile (spec §4)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema

from pipeline.compliance import (
    assert_within_retention,
    assert_governance_complete,
)
from pipeline.models import Profile, MediaItem, GovernanceBlock

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "02-normalized.schema.json"


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


def run(handle: str, project_dir: Path) -> Path:
    """Run Stage 2 for *handle*, reading 01-raw.json and writing 02-normalized.json.

    Returns the path to the written artifact.
    """
    raw_path = project_dir / "01-raw.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Stage 1 artifact not found: {raw_path}")

    with open(raw_path) as fh:
        raw = json.load(fh)

    gov_dict = raw["_governance"]

    # Step 1: retention check
    assert_within_retention(gov_dict, handle=handle)

    # Step 2: governance completeness
    assert_governance_complete(gov_dict)

    # Step 3: parse into Pydantic models
    raw_profile = raw["raw_profile"]
    raw_media = raw["raw_media"]

    media_items = [MediaItem(**item) for item in raw_media]
    governance = GovernanceBlock(**gov_dict)

    profile = Profile(
        handle=raw_profile.get("handle", handle),
        platform=raw_profile.get("platform", "instagram"),
        profile_id=raw_profile.get("profile_id"),
        display_name=raw_profile.get("display_name"),
        bio=raw_profile.get("bio"),
        website=raw_profile.get("website"),
        is_verified=raw_profile.get("is_verified", False),
        is_business=raw_profile.get("is_business", False),
        account_type=raw_profile.get("account_type"),
        followers=raw_profile["followers"],
        following=raw_profile["following"],
        post_count=raw_profile["post_count"],
        snapshot_at=raw_profile["snapshot_at"],
        media=media_items,
        audience=None,
        governance=governance,
    )

    # Step 4: validate against schema
    normalized = profile.model_dump()
    schema = _load_schema()
    jsonschema.validate(normalized, schema)

    # Step 5: atomic write
    out_path = project_dir / "02-normalized.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(normalized, fh, indent=2)
    # Optionally merge Stage 1B enrichment signals (additive — never overwrites existing fields)
    enrichment_path = project_dir / "enrichment_map.json"
    if enrichment_path.exists():
        try:
            with open(enrichment_path) as fh:
                enrichment = json.load(fh)
            doc["enrichment_signals"] = enrichment.get("signals", [])
            doc["enrichment_entity_count"] = len(enrichment.get("entity_pool", []))
        except Exception:
            pass  # enrichment is additive — Stage 2 never fails because of it

    os.replace(tmp_path, out_path)

    return out_path
