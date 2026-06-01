"""Fellegi-Sunter log-LR scoring for UIL candidates (spec 0011 §3, T13).

Named constants are the single source of truth for all probability priors
and decision thresholds. Values are literature-grounded (Fellegi & Sunter 1969,
Larsen & Winkler 2001) tuned for precision over recall (v3a goal).
"""
from __future__ import annotations

import math

# ── Per-family m/u priors ─────────────────────────────────────────────────────
# m_i = P(agreement | same entity)   (probability agreement given match)
# u_i = P(agreement | diff entity)   (probability agreement given non-match)
M_PRIORS: dict[str, float] = {
    "handle":         0.90,
    "display_name":   0.85,
    "profile_photo":  0.80,
    "website":        0.88,
    "bio":            0.70,
}
U_PRIORS: dict[str, float] = {
    "handle":         0.05,
    "display_name":   0.15,
    "profile_photo":  0.02,
    "website":        0.03,
    "bio":            0.20,
}

# ── Decision thresholds (on raw log-LR) ──────────────────────────────────────
T_LINK: float = 2.0       # log-LR ≥ T_LINK → "link"
T_POSSIBLE: float = 0.5   # T_POSSIBLE ≤ log-LR < T_LINK → "possible_link"
                           # log-LR < T_POSSIBLE → "non_link"

SURFACE_THRESHOLD: float = 0.7  # confidence ≥ this AND human_review=approved → surfaceable


def _logistic(x: float) -> float:
    """Sigmoid mapping log-LR → [0, 1]."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def score_candidate(feature_evidences: list[dict]) -> tuple[float, float, str]:
    """Compute (confidence, likelihood_ratio, classification) from feature evidences.

    Each evidence dict must have ``feature`` and ``agreement`` (0–1).
    Returns:
        confidence      – logistic(log_lr) ∈ [0, 1]
        likelihood_ratio – raw composite log-LR (for reviewer transparency)
        classification  – "link" | "possible_link" | "non_link"
    """
    log_lr = 0.0
    for ev in feature_evidences:
        feature = ev["feature"]
        agreement = ev["agreement"]
        m = M_PRIORS.get(feature, 0.5)
        u = U_PRIORS.get(feature, 0.5)
        if agreement >= 0.5:
            log_lr += math.log(m / u) * agreement
        else:
            log_lr += math.log((1 - m) / (1 - u)) * (1 - agreement)

    confidence = _logistic(log_lr)

    if log_lr >= T_LINK:
        classification = "link"
    elif log_lr >= T_POSSIBLE:
        classification = "possible_link"
    else:
        classification = "non_link"

    return confidence, log_lr, classification
