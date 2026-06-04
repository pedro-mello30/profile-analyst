"""Data models for account discovery (spec-0018 §4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SeedAccount:
    handle: str
    platform: str
    bio_text: str = ""
    bio_urls: list[str] = field(default_factory=list)
    discovery_run_id: str = ""
    seeded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AttributionStep:
    adapter_id: str
    from_entity_type: str
    from_entity_value: str
    relationship: str

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "from_entity_type": self.from_entity_type,
            "from_entity_value": self.from_entity_value,
            "relationship": self.relationship,
        }


@dataclass
class DiscoveredAccount:
    account_id: str
    platform: str
    handle: str
    profile_url: str
    confidence: float
    method: str
    source_adapter_id: str
    attribution_chain: list[AttributionStep]
    discovered_at: datetime
    verified: bool = False

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "handle": self.handle,
            "profile_url": self.profile_url,
            "confidence": self.confidence,
            "method": self.method,
            "source_adapter_id": self.source_adapter_id,
            "attribution_chain": [s.to_dict() for s in self.attribution_chain],
            "discovered_at": self.discovered_at.isoformat(),
            "verified": self.verified,
        }


@dataclass
class AccountRelationship:
    from_account_id: str
    to_account_id: str
    relationship_type: str
    confidence: float
    source_adapter_id: str

    def to_dict(self) -> dict:
        return {
            "from_account_id": self.from_account_id,
            "to_account_id": self.to_account_id,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "source_adapter_id": self.source_adapter_id,
        }


@dataclass
class DiscoveryStats:
    adapters_run: int = 0
    accounts_found: int = 0
    relationships_found: int = 0
    depth_reached: int = 0
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "adapters_run": self.adapters_run,
            "accounts_found": self.accounts_found,
            "relationships_found": self.relationships_found,
            "depth_reached": self.depth_reached,
            "elapsed_s": self.elapsed_s,
        }


@dataclass
class DiscoveryManifest:
    seed_handle: str
    seed_platform: str
    run_id: str
    started_at: datetime
    discovered_accounts: list[DiscoveredAccount]
    relationships: list[AccountRelationship]
    stats: DiscoveryStats
    limit_reached: bool
    completed_at: datetime | None = None
    governance: Any | None = None

    def to_dict(self) -> dict:
        return {
            "seed_handle": self.seed_handle,
            "seed_platform": self.seed_platform,
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "discovered_accounts": [a.to_dict() for a in self.discovered_accounts],
            "relationships": [r.to_dict() for r in self.relationships],
            "stats": self.stats.to_dict(),
            "limit_reached": self.limit_reached,
            "governance": self.governance.to_dict() if hasattr(self.governance, "to_dict") else self.governance,
        }
