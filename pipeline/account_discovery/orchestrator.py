"""Discovery orchestrator: wires seed entities → engine → manifest (spec-0018 §3)."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.account_discovery.engine import DiscoveryEngine, DiscoveryEngineState
from pipeline.account_discovery.models import (
    DiscoveryManifest,
    DiscoveryStats,
)
from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.scheduler import DiscoveryConfig


# ---------------------------------------------------------------------------
# Internal seed entity type
# ---------------------------------------------------------------------------

class _SeedEntity:
    """Minimal duck-typed entity with .type and .value attrs."""

    __slots__ = ("type", "value")

    def __init__(self, entity_type: str, value: str) -> None:
        self.type = entity_type
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover
        return f"_SeedEntity(type={self.type!r}, value={self.value!r})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover(
    handle: str,
    adapters: list,
    *,
    bio_text: str = "",
    bio_urls: list[str] | None = None,
    output_dir: Path | None = None,
    config: DiscoveryConfig | None = None,
) -> DiscoveryManifest:
    """Run the account-discovery pipeline and return a :class:`DiscoveryManifest`.

    Parameters
    ----------
    handle:
        Instagram handle that seeds the discovery run.
    adapters:
        List of :class:`~pipeline.account_discovery.contracts.DiscoveryAdapter`
        instances to use.
    bio_text:
        Raw biography text (optional). Produces a ``bio_text`` seed entity when
        non-empty.
    bio_urls:
        List of URLs extracted from the biography (optional). Each produces a
        ``url`` seed entity.
    output_dir:
        When provided the manifest is written atomically to
        ``output_dir/00-discovery.json``.
    config:
        Runtime configuration; defaults to :class:`DiscoveryConfig` with its
        default values.
    """
    if config is None:
        config = DiscoveryConfig()

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    # 1. Build seed entities
    seed_entities: list[_SeedEntity] = [_SeedEntity("instagram_handle", handle)]
    if bio_text:
        seed_entities.append(_SeedEntity("bio_text", bio_text))
    for url in (bio_urls or []):
        seed_entities.append(_SeedEntity("url", url))

    # 2. Create pool + state
    pool = AccountPool()
    state = DiscoveryEngineState()

    # 3. Run engine (mutates pool + state in place)
    DiscoveryEngine(adapters, config).run(pool, seed_entities, state, run_id=run_id)

    elapsed = time.monotonic() - t0
    completed_at = datetime.now(timezone.utc)

    # 4. Build manifest
    accounts = pool.all_accounts()
    stats = DiscoveryStats(
        adapters_run=state.total_adapter_runs,
        accounts_found=len(accounts),
        relationships_found=0,
        depth_reached=0,
        elapsed_s=elapsed,
    )

    governance: Any = None
    if state.governance_report is not None:
        governance = state.governance_report

    manifest = DiscoveryManifest(
        seed_handle=handle,
        seed_platform="instagram",
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        discovered_accounts=accounts,
        relationships=[],
        stats=stats,
        limit_reached=state.limit_reached,
        governance=governance,
    )

    # 5. Atomic artifact write
    if output_dir is not None:
        _write_artifact(manifest, output_dir)

    return manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_artifact(manifest: DiscoveryManifest, output_dir: Path) -> None:
    """Atomically write manifest to ``output_dir/00-discovery.json``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "00-discovery.json"
    tmp = output_dir / f"00-discovery.json.{uuid.uuid4().hex}.tmp"
    doc = manifest.to_dict()
    # Ensure governance is always present as a key (even if None)
    if "governance" not in doc:
        doc["governance"] = None
    tmp.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
