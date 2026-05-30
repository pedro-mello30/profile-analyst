"""GDPR Art.22 automated-decision-making compliance helpers (spec §9.1)."""
from __future__ import annotations

from pipeline.compliance.tos import ComplianceError

# All four v1 scores affect campaign selection → Art.22 always applies in v1.
SELECTION_SCORES: set[str] = {
    "engagement_quality",
    "authenticity",
    "sponsorship_transparency",
    "brand_safety",
}


def art22_applies(scores: dict) -> bool:
    """Return True if any score in ``scores`` is a campaign-selection-affecting score."""
    return bool(SELECTION_SCORES & set(scores.keys()))


def assert_scores_explainable(scores: dict) -> None:
    """Raise ComplianceError if any score has an empty signals list (Art.22 §1)."""
    for name, score in scores.items():
        signals = score.get("signals") if isinstance(score, dict) else getattr(score, "signals", None)
        if not signals:
            raise ComplianceError(
                f"Score '{name}' has an empty signals list. "
                "Art.22 requires a meaningful explanation of the logic. "
                "Add at least one signal entry before emitting the dossier."
            )


def build_compliance_flags(
    *,
    governance: dict,
    scores: dict,
    art9_feature_ids: list[str],
    ftc_disclosure_status: str,
    handle: str,
) -> dict:
    """Assemble the compliance_flags block for the dossier (spec §8)."""
    applies = art22_applies(scores)
    return {
        "gdpr_basis": governance.get("gdpr_basis", "UNKNOWN"),
        "art22_applies": applies,
        "art22_human_review_required": applies,
        "art9_features": list(art9_feature_ids),
        "ftc_disclosure_status": ftc_disclosure_status,
        "tos_compliant_source": governance.get("tos_compliant_at_ingest", False),
        "opt_out_path": f"DELETE /profiles/{handle}",
    }


def gate_art9_report_exposure(art9_ids: list[str], *, expose_art9: bool) -> list[str]:
    """Return the list of Art.9 feature_ids to include in the report.

    When expose_art9 is False (default), returns a redaction placeholder list;
    consumers should render "<redacted: Art.9, opt-in required>" for each entry.
    """
    if expose_art9:
        return list(art9_ids)
    return ["<redacted: Art.9, opt-in required>"] if art9_ids else []
