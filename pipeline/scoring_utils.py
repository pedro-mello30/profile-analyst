"""Shared scoring primitives used by Stage 3 (deterministic features) and Stage 6 (dossier scores)."""
from __future__ import annotations

# Midpoint of spec §5.1 ER benchmark ranges (ClickAnalytic Dec 2025)
TIER_BENCHMARK_ER: dict[str, float] = {
    "Nano": 11.5,
    "Micro": 4.4,
    "Mid": 0.73,
    "Macro": 1.02,
    "Mega": 1.10,
    "Celebrity": 1.20,
}

EQS_WEIGHTS: dict[str, float] = {
    "er": 0.40,
    "comments": 0.20,
    "consistency": 0.20,
    "ratio": 0.20,
}

AUTH_WEIGHTS: dict[str, float] = {
    "completeness": 0.25,
    "ratio": 0.25,
}

# Follower thresholds for tier classification (spec §5.1)
_TIER_THRESHOLDS = [
    (1_000, "Nano"),
    (10_000, "Micro"),
    (50_000, "Mid"),
    (500_000, "Macro"),
    (1_000_000, "Mega"),
]


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp x to [lo, hi]."""
    return max(lo, min(hi, x))


def follower_tier(followers: int) -> str:
    """Return the influencer tier label for a given follower count."""
    for threshold, label in _TIER_THRESHOLDS:
        if followers < threshold:
            return label
    return "Celebrity"


def er_vs_benchmark(er: float, tier: str) -> float:
    """Score ER relative to tier benchmark: at benchmark → 50; at 2× → 100."""
    benchmark = TIER_BENCHMARK_ER.get(tier, 1.0)
    if benchmark == 0:
        return 0.0
    return clamp((er / benchmark) * 50.0)


def _ratio_reasonableness(ratio: float) -> float:
    """Score follower/following ratio per spec §8 formula."""
    if ratio < 0.1:
        return 20.0
    if ratio < 1.0:
        return clamp(ratio * 100.0)
    if ratio <= 50.0:
        return 100.0
    return clamp(100.0 - (ratio - 50.0) * 0.5)
