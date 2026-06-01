"""Cohort discovery for Stage 5 — glob, sort, >=2 guard (spec 0012 §3, T6-T7)."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.models import Profile


class CohortValidationError(ValueError):
    """Raised when the on-disk cohort cannot support graph operations."""


def discover_cohort(projects_dir: Path | str) -> list[Profile]:
    """Return all profiles found under ``projects_dir/*/02-normalized.json``.

    Profiles are sorted deterministically by handle. Raises ``CohortValidationError``
    when fewer than 2 profiles exist (graph operations require ≥ 2 creators).
    """
    projects_dir = Path(projects_dir)
    profiles: list[Profile] = []

    for norm_path in sorted(projects_dir.glob("*/02-normalized.json")):
        try:
            with open(norm_path) as f:
                data = json.load(f)
            profiles.append(Profile.model_validate(data))
        except Exception:
            # Skip malformed artifacts; the caller gets a partial cohort.
            pass

    profiles.sort(key=lambda p: p.handle)

    if len(profiles) < 2:
        raise CohortValidationError(
            f"Graph operations require ≥ 2 creator profiles; "
            f"found {len(profiles)} under {projects_dir}"
        )

    return profiles
