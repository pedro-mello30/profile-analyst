"""Shared scoring primitives used by Stage 3 (deterministic features) and Stage 6 (dossier scores)."""
from __future__ import annotations

from observability import trace, TOOL, log_signal_lineage

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


@trace(TOOL)
def calculate_fraud_risk(
    follower_growth_anomaly: float = 0.0,
    comment_quality_score: float = 0.5,
    engagement_rate: float = 0.03,
    community_size: float = 0.0,
    centrality_score: float = 0.0,
) -> float:
    """Compute a fraud-risk score [0, 1] and log signal lineage (GDPR Art. 22).

    Combines heuristic signals from Stage 3 / Stage 9 GDS into a single score.
    Signals are logged to the active MLflow run for audit (spec §6, D5).

    Args:
        follower_growth_anomaly: 0=normal growth, 1=highly anomalous spike.
        comment_quality_score:   0=low quality (bots), 1=genuine engagement.
        engagement_rate:         Raw ER (e.g. 0.04 = 4%).
        community_size:          Normalised community/pod size from Louvain (0–1).
        centrality_score:        Betweenness/PageRank centrality signal (0–1).

    Returns:
        Fraud-risk score in [0.0, 1.0] — higher = more risk.
    """
    signals = {
        "follower_growth_anomaly": follower_growth_anomaly,
        "comment_quality_score": comment_quality_score,
        "engagement_rate": engagement_rate,
        "community_size": community_size,
        "centrality_score": centrality_score,
    }

    # Tier-normalised ER: 0.05 (~Macro benchmark) used as midpoint reference
    er_anomaly = clamp(1.0 - engagement_rate / 0.05, 0.0, 1.0)

    score = clamp(
        follower_growth_anomaly * 0.30
        + (1.0 - comment_quality_score) * 0.25
        + er_anomaly * 0.20
        + community_size * 0.15
        + centrality_score * 0.10,
        0.0,
        1.0,
    )

    log_signal_lineage("fraud_risk_score", signals, score)
    return score


def _ratio_reasonableness(ratio: float) -> float:
    """Score follower/following ratio per spec §8 formula."""
    if ratio < 0.1:
        return 20.0
    if ratio < 1.0:
        return clamp(ratio * 100.0)
    if ratio <= 50.0:
        return 100.0
    return clamp(100.0 - (ratio - 50.0) * 0.5)
