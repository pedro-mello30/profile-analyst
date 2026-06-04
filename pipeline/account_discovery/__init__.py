"""pipeline.account_discovery — cross-platform account discovery module (spec-0018)."""
from __future__ import annotations

from pipeline.account_discovery.models import DiscoveredAccount, DiscoveryManifest

try:
    from pipeline.account_discovery.orchestrator import discover
except ImportError:
    pass

__all__ = [
    "DiscoveredAccount",
    "DiscoveryManifest",
]
