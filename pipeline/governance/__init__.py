"""pipeline.governance — standalone runtime governance module (spec-0020).

Public surface:
  validate_adapter_contract         EnrichmentAdapter contract check
  validate_discovery_adapter_contract  DiscoveryAdapter contract check
  validate_enricher_contract        Enricher contract check
  assert_provenance_chain           Provenance check at manifest build
  RobotsPolicy                      robots.txt check with TTL cache
  RateLimiter                       Token-bucket rate limiter
  RateLimitExceeded                 Raised when wait > timeout_s
  normalize_confidence              Clamp + warn for out-of-range values
  compute_coverage                  CoverageReport from pool + adapters
  build_report                      Create a GovernanceReport for a run
  AdapterContractError, ProvenanceError
  PolicyDecision, RateLimitToken, ContractViolation, CoverageReport, GovernanceReport
"""
from __future__ import annotations

from pipeline.governance.compliance import (
    AdapterContractError,
    ProvenanceError,
    assert_provenance_chain,
    validate_adapter_contract,
    validate_discovery_adapter_contract,
    validate_enricher_contract,
)
from pipeline.governance.metrics import compute_coverage, normalize_confidence
from pipeline.governance.models import (
    ContractViolation,
    CoverageReport,
    GovernanceReport,
    PolicyDecision,
    RateLimitToken,
)
from pipeline.governance.policies import RateLimitExceeded, RateLimiter, RobotsPolicy


def build_report(run_id: str, module: str) -> GovernanceReport:
    """Create a fresh GovernanceReport for a new run."""
    from datetime import datetime, timezone
    return GovernanceReport(
        run_id=run_id,
        module=module,
        started_at=datetime.now(timezone.utc),
    )


__all__ = [
    "validate_adapter_contract",
    "validate_discovery_adapter_contract",
    "validate_enricher_contract",
    "assert_provenance_chain",
    "AdapterContractError",
    "ProvenanceError",
    "RobotsPolicy",
    "RateLimiter",
    "RateLimitExceeded",
    "normalize_confidence",
    "compute_coverage",
    "build_report",
    "PolicyDecision",
    "RateLimitToken",
    "ContractViolation",
    "CoverageReport",
    "GovernanceReport",
]
