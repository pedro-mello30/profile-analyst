"""Surfaceable gate for UIL candidates (spec 0011 §3, T14).

Gate rule (spec D6):
  surfaceable = (confidence ≥ SURFACE_THRESHOLD) AND (human_review_status == "approved")
  manual_review_required = confidence < SURFACE_THRESHOLD
  multi_match_flag = True on every candidate in a platform group with >1 link/possible_link
  Art.9-adjacent targets without consent_record_id are NEVER surfaceable.
  pHash alone can NEVER push a candidate to surfaceable.
"""
from __future__ import annotations

from pipeline.linkage.scoring import SURFACE_THRESHOLD

_ART9_ADJACENT_NICHES = {
    "health", "fitness", "wellness", "mental health", "lgbtq", "lgbtq+",
    "queer", "religion", "faith", "political", "activism",
}


def _is_art9_adjacent(candidate: dict) -> bool:
    """Heuristic: flag candidate if their bio/handle signals Art.9 category."""
    bio = (candidate.get("bio") or "").lower()
    return any(kw in bio for kw in _ART9_ADJACENT_NICHES)


def _phash_only(feature_evidences: list[dict]) -> bool:
    """Return True if pHash is the only evidence with agreement > 0.5."""
    significant = [e for e in feature_evidences if e["agreement"] > 0.5]
    return len(significant) == 1 and significant[0]["feature"] == "profile_photo"


def apply_gate(
    candidates: list[dict],
    *,
    platform_classifications: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Apply the surfaceable gate to a list of partially-scored candidate dicts.

    Each candidate dict must already have:
        confidence, feature_evidence, classification,
        human_review_status, consent_record_id
    This function adds/overwrites:
        surfaceable, manual_review_required, multi_match_flag
    """
    # Build multi_match_flag: per platform, count link/possible_link candidates
    from collections import defaultdict
    platform_hits: dict[str, int] = defaultdict(int)
    for c in candidates:
        if c.get("classification") in {"link", "possible_link"}:
            platform_hits[c["platform"]] += 1

    result = []
    for c in candidates:
        conf = c["confidence"]
        review = c.get("human_review_status", "pending")
        consent = c.get("consent_record_id")
        evidence = c.get("feature_evidence", [])

        manual_review_required = conf < SURFACE_THRESHOLD
        multi_match_flag = platform_hits[c["platform"]] > 1

        # Art.9 gate: never surfaceable without consent_record_id
        art9_blocked = _is_art9_adjacent(c) and consent is None

        # pHash-alone block: pHash is biometric-adjacent, can't be sole decider
        phash_blocked = _phash_only(evidence)

        surfaceable = (
            conf >= SURFACE_THRESHOLD
            and review == "approved"
            and not art9_blocked
            and not phash_blocked
        )

        result.append({
            **c,
            "manual_review_required": manual_review_required,
            "multi_match_flag": multi_match_flag,
            "surfaceable": surfaceable,
        })

    return result
