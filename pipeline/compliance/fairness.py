"""Fairness & bias guards for feature outputs (spec §9.5)."""
from __future__ import annotations

from pipeline.compliance.tos import ComplianceError

# Feature IDs that must never appear in pipeline output
FORBIDDEN_FEATURE_IDS: set[str] = {
    "binary_gender",
    "ethnicity",
    "race",
    "race_ethnicity",
    "gender_binary",
    "inferred_ethnicity",
    "inferred_race",
}

# Demographic features that ARE allowed (continuous / inferred only)
ALLOWED_DEMOGRAPHIC: set[str] = {
    "audience_gender_skew",
    "age_group",
}


def strip_forbidden_features(features: list[dict]) -> tuple[list[dict], list[str]]:
    """Remove features with forbidden feature_ids.

    Returns (kept_features, dropped_feature_ids).
    """
    kept: list[dict] = []
    dropped: list[str] = []
    for feat in features:
        fid = feat.get("feature_id", "")
        if fid in FORBIDDEN_FEATURE_IDS:
            dropped.append(fid)
        else:
            kept.append(feat)
    return kept, dropped


def assert_demographic_inference_humility(features: list[dict]) -> None:
    """Raise ComplianceError if any demographic feature claims certainty (confidence >= 1.0)
    or uses method != 'inferred' (spec §9.5 — demographic inferences must never be presented
    as ground truth).
    """
    for feat in features:
        fid = feat.get("feature_id", "")
        if fid in ALLOWED_DEMOGRAPHIC:
            confidence = feat.get("confidence", 0.0)
            method = feat.get("method", "")
            if confidence >= 1.0:
                raise ComplianceError(
                    f"Demographic feature '{fid}' has confidence=1.0. "
                    "Demographic inferences must never be presented as ground truth (spec §9.5)."
                )
            if method != "inferred":
                raise ComplianceError(
                    f"Demographic feature '{fid}' has method='{method}'. "
                    "Must be 'inferred' per spec §9.5 (never 'computed' or 'llm' for demographics)."
                )
