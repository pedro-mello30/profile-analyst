"""Compliance gate for Stage 5 associations (spec 0012 §3, T19).

Art.9 community scan: flags communities whose aggregate niche/hashtag tokens
match Art.9 categories. Art.22 signals enforcement: raises if any neighbor
edge has an empty signals list.
"""
from __future__ import annotations

import networkx as nx

from pipeline.compliance.art9 import ART9_TEXT_PATTERNS
from pipeline.models import Profile


class AssociationsGateError(ValueError):
    """Raised when an edge has empty signals[] — violates Art.22 explainability."""


def _bio_has_art9(bio: str) -> bool:
    """Return True if the bio text matches any Art.9 category pattern."""
    for pattern in ART9_TEXT_PATTERNS.values():
        if pattern.search(bio):
            return True
    return False


def scan_community_art9(
    membership: dict[str, int],
    profiles: list[Profile],
) -> dict[int, bool]:
    """Return {community_id → art9_risk bool} for each community.

    A community is Art.9-adjacent if any member's bio triggers Art.9 patterns.
    """
    profile_map = {p.handle: p for p in profiles}

    community_ids: set[int] = set(membership.values())
    community_art9: dict[int, bool] = {cid: False for cid in community_ids}

    for handle, cid in membership.items():
        if community_art9[cid]:
            continue  # already flagged
        profile = profile_map.get(handle)
        if not profile:
            continue
        bio = profile.bio or ""
        if _bio_has_art9(bio):
            community_art9[cid] = True

    return community_art9


def enforce_art22_signals(neighbors: list[dict]) -> None:
    """Raise AssociationsGateError if any neighbor edge has an empty signals list."""
    for nbr in neighbors:
        if not nbr.get("signals"):
            raise AssociationsGateError(
                f"Neighbor edge to '{nbr.get('handle')}' has empty signals[] — "
                "violates Art.22 explainability requirement."
            )
