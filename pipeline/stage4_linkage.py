"""Stage 4 — Cross-Platform Identity Linkage (UIL v3a) (spec 0011 §3, T17).

run(handle, project_dir) is the single entry point:
  uil_lia_gate() → adapter fetch → blocking → features → scoring → gate
  → jsonschema validate → atomic write 04-linkage.json

Idempotent — only writes 04-linkage.json; reads 02-normalized.json + fixture.
Stage 4 is opt-in: --stage all never includes it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from adapters.cross_platform.sample_uil import SampleUILAdapter
from pipeline.compliance.tos import uil_lia_gate
from pipeline.linkage.blocking import block_candidates
from pipeline.linkage.features import compute_agreement_vector
from pipeline.linkage.gate import apply_gate
from pipeline.linkage.scoring import score_candidate

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "04-linkage.schema.json"


def _load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def _load_profile(project_dir: Path) -> dict:
    norm_path = project_dir / "02-normalized.json"
    if not norm_path.exists():
        raise FileNotFoundError(f"02-normalized.json not found at {norm_path}")
    with open(norm_path) as f:
        return json.load(f)


def run(handle: str, project_dir: Path | str) -> Path:
    """Execute Stage 4 UIL for ``handle``. Returns path to 04-linkage.json."""
    project_dir = Path(project_dir)

    # ── 0. LIA gate (must be first) ──────────────────────────────────────────
    uil_lia_gate(handle)

    # ── 1. Load normalized profile ───────────────────────────────────────────
    profile = _load_profile(project_dir)
    governance = profile.get("governance", {})

    # ── 2. Fetch candidates via SampleUILAdapter ──────────────────────────────
    adapter = SampleUILAdapter()
    raw_candidates = adapter.fetch_candidates(handle)

    # ── 3. Blocking ───────────────────────────────────────────────────────────
    ordered = block_candidates(handle, raw_candidates)

    # ── 4. Features + scoring + gate ─────────────────────────────────────────
    scored: list[dict] = []
    for cand in ordered:
        vec = compute_agreement_vector(profile, cand)
        confidence, lr, classification = score_candidate(vec.evidences)
        scored.append({
            **cand,
            "confidence": round(confidence, 6),
            "likelihood_ratio": round(lr, 6),
            "feature_evidence": vec.evidences,
            "classification": classification,
            "human_review_status": cand.get("human_review_status", "pending"),
            "consent_record_id": cand.get("consent_record_id", None),
        })

    gated = apply_gate(scored)

    # ── 5. Strip extra fixture fields — keep only schema-defined keys ────────
    _CANDIDATE_KEYS = {
        "platform", "candidate_handle", "confidence", "likelihood_ratio",
        "feature_evidence", "classification", "multi_match_flag",
        "manual_review_required", "human_review_status", "consent_record_id",
        "surfaceable",
    }
    gated = [{k: v for k, v in c.items() if k in _CANDIDATE_KEYS} for c in gated]

    # ── 6. Build document ─────────────────────────────────────────────────────
    doc = {
        "handle": handle,
        "method_version": "v3a",
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "governance": governance,
        "candidates": gated,
    }

    # ── 6. Schema validate ───────────────────────────────────────────────────
    schema = _load_schema()
    jsonschema.validate(doc, schema)

    # ── 7. Atomic write ───────────────────────────────────────────────────────
    out_path = project_dir / "04-linkage.json"
    tmp_fd, tmp_name = tempfile.mkstemp(dir=project_dir, prefix=".04-linkage-")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp_name, out_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    return out_path
