"""Stage 1 INGEST — fetch raw profile, enforce ToS gate, write 01-raw.json (spec §3)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from adapters.base import SourceAdapter
from pipeline.compliance import (
    enforce_tos_gate,
    build_governance_block,
    assert_governance_complete,
)

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "01-raw.schema.json"


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


def run(handle: str, adapter: SourceAdapter, project_dir: Path) -> Path:
    """Run Stage 1 for *handle* using *adapter*, writing 01-raw.json to *project_dir*.

    Returns the path to the written artifact.
    """
    # Step 1: ToS gate
    enforce_tos_gate(adapter)

    # Step 2: fetch
    raw_profile = adapter.fetch_profile(handle)
    raw_media = adapter.fetch_media(handle, limit=20)

    # Step 3: governance block
    ingested_at = datetime.now(timezone.utc)
    subject_jurisdiction = raw_profile.get("location") or "UNKNOWN"
    governance = build_governance_block(
        adapter,
        subject_jurisdiction=subject_jurisdiction,
        ingested_at=ingested_at,
    )
    assert_governance_complete(governance)

    # Step 4: assemble + validate
    record = {
        "handle": handle,
        "platform": raw_profile.get("platform", "instagram"),
        "_governance": governance,
        "raw_profile": raw_profile,
        "raw_media": raw_media,
    }
    schema = _load_schema()
    jsonschema.validate(record, schema)

    # Step 5: atomic write
    project_dir.mkdir(parents=True, exist_ok=True)
    out_path = project_dir / "01-raw.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(record, fh, indent=2)
    os.replace(tmp_path, out_path)

    return out_path
