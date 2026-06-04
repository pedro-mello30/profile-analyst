"""Data models for governance decisions and reports (spec-0020 §4)."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    checked_url: str
    policy_type: str
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RateLimitToken:
    adapter_id: str
    acquired_at: datetime
    wait_s: float

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@dataclass
class ContractViolation:
    adapter_id: str
    field: str
    expected: str
    got: str
    message: str


@dataclass
class CoverageReport:
    run_id: str
    module: str
    adapters_registered: int
    adapters_run: int
    adapters_skipped: int
    adapters_failed: int
    entity_types_expected: set
    entity_types_discovered: set
    coverage_ratio: float
    per_adapter_coverage: dict
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["entity_types_expected"] = sorted(d["entity_types_expected"])
        d["entity_types_discovered"] = sorted(d["entity_types_discovered"])
        d["generated_at"] = self.generated_at.isoformat()
        return d


@dataclass
class GovernanceReport:
    run_id: str
    module: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    policy_decisions: List[PolicyDecision] = field(default_factory=list)
    violations: List[ContractViolation] = field(default_factory=list)
    coverage: Optional[CoverageReport] = None
    total_rate_limit_waits: int = 0
    total_wait_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "module": self.module,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "policy_decisions": [
                {
                    "allowed": d.allowed,
                    "reason": d.reason,
                    "checked_url": d.checked_url,
                    "policy_type": d.policy_type,
                    "decided_at": d.decided_at.isoformat(),
                }
                for d in self.policy_decisions
            ],
            "violations": [
                {
                    "adapter_id": v.adapter_id,
                    "field": v.field,
                    "expected": v.expected,
                    "got": v.got,
                    "message": v.message,
                }
                for v in self.violations
            ],
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "total_rate_limit_waits": self.total_rate_limit_waits,
            "total_wait_s": self.total_wait_s,
        }
