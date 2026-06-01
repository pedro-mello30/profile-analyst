"""pipeline.compliance — public API re-exports (spec §9)."""
from pipeline.compliance.tos import (
    TosComplianceError,
    ComplianceError,
    UilLiaError,
    enforce_tos_gate,
    build_governance_block,
    assert_governance_complete,
    allow_noncompliant,
    uil_lia_gate,
    REQUIRED_GOVERNANCE_FIELDS,
)
from pipeline.compliance.art9 import (
    Art9Category,
    Art9Finding,
    Art9Scanner,
    ART9_SENSITIVE_FEATURE_IDS,
    ART9_NICHE_VALUES,
    ART9_TEXT_PATTERNS,
)
from pipeline.compliance.art22 import (
    SELECTION_SCORES,
    art22_applies,
    assert_scores_explainable,
    build_compliance_flags,
    gate_art9_report_exposure,
)
from pipeline.compliance.fairness import (
    FORBIDDEN_FEATURE_IDS,
    ALLOWED_DEMOGRAPHIC,
    strip_forbidden_features,
    assert_demographic_inference_humility,
)
from pipeline.compliance.erasure import (
    ErasureReceipt,
    erase_profile,
    is_expired,
    assert_within_retention,
    gc_sweep,
)

__all__ = [
    # tos
    "TosComplianceError",
    "ComplianceError",
    "UilLiaError",
    "enforce_tos_gate",
    "build_governance_block",
    "assert_governance_complete",
    "allow_noncompliant",
    "uil_lia_gate",
    "REQUIRED_GOVERNANCE_FIELDS",
    # art9
    "Art9Category",
    "Art9Finding",
    "Art9Scanner",
    "ART9_SENSITIVE_FEATURE_IDS",
    "ART9_NICHE_VALUES",
    "ART9_TEXT_PATTERNS",
    # art22
    "SELECTION_SCORES",
    "art22_applies",
    "assert_scores_explainable",
    "build_compliance_flags",
    "gate_art9_report_exposure",
    # fairness
    "FORBIDDEN_FEATURE_IDS",
    "ALLOWED_DEMOGRAPHIC",
    "strip_forbidden_features",
    "assert_demographic_inference_humility",
    # erasure
    "ErasureReceipt",
    "erase_profile",
    "is_expired",
    "assert_within_retention",
    "gc_sweep",
]
