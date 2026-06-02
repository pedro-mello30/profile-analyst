"""Adapter contract for the enrichment engine (spec 0014 §4)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pipeline.enrichment.entity import Entity, ENTITY_TYPES

_VALID_TIERS = frozenset({"seed", "fast", "medium", "slow"})
_VALID_GDPR = frozenset({"LEGITIMATE_INTERESTS", "CONSENT", "NONE"})
_VALID_CATS = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})

_REQUIRED_ATTRS = (
    "adapter_id", "display_name", "requires", "produces", "tier", "priority",
    "cost_usd", "timeout_s", "retry_max", "rate_limit_rpm", "ttl_hours",
    "min_confidence", "max_instances", "osint_risk", "secrets_required",
    "gdpr_basis", "data_category", "tos_compliant",
)


class AdapterContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterConfig:
    profile_id: str
    run_id: str
    max_depth: int
    max_cost_usd: float
    max_runtime_s: int
    secrets: dict[str, str]
    osint_enabled: bool
    cache_enabled: bool
    dry_run: bool


@dataclass
class Signal:
    key: str
    value: Any
    unit: str | None
    confidence: float
    method: str       # "api" | "scrape" | "osint" | "computed"
    source: str
    osint_risk: bool


@dataclass
class AdapterResult:
    adapter_id: str
    entities: list[Entity]
    signals: list[Signal]
    error: str | None
    cached: bool
    ran_at: str
    cost_usd: float
    duration_s: float = 0.0


class EnrichmentAdapter(ABC):
    """Base class for all enrichment adapters. Validates contract at import time."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip validation for the ABC itself and any intermediate abstract classes
        if getattr(cls, "__abstractmethods__", None):
            return
        errors = []
        for attr in _REQUIRED_ATTRS:
            if not hasattr(cls, attr):
                errors.append(f"missing required class attribute: {attr!r}")
        if hasattr(cls, "tier") and cls.tier not in _VALID_TIERS:
            errors.append(f"tier={cls.tier!r} not in {_VALID_TIERS}")
        if hasattr(cls, "gdpr_basis") and cls.gdpr_basis not in _VALID_GDPR:
            errors.append(f"gdpr_basis={cls.gdpr_basis!r} not in {_VALID_GDPR}")
        if hasattr(cls, "data_category") and cls.data_category not in _VALID_CATS:
            errors.append(f"data_category={cls.data_category!r} not in {_VALID_CATS}")
        if hasattr(cls, "requires"):
            bad = [t for t in cls.requires if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"requires contains unknown entity types: {bad}")
        if hasattr(cls, "produces"):
            bad = [t for t in cls.produces if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"produces contains unknown entity types: {bad}")
        if hasattr(cls, "min_confidence") and not (0.0 <= cls.min_confidence <= 1.0):
            errors.append(f"min_confidence={cls.min_confidence} out of [0.0, 1.0]")
        if errors:
            raise AdapterContractError(
                f"Adapter {cls.__name__!r} has {len(errors)} contract violation(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    @abstractmethod
    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult: ...
