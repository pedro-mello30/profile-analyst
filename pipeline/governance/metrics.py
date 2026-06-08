"""Coverage and confidence normalization (spec-0020 §7)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from pipeline.governance.models import CoverageReport

logger = logging.getLogger(__name__)


def normalize_confidence(value: float, *, warn_if_clamped: bool = True) -> float:
    """Clamp confidence to [0.0, 1.0]. Logs WARNING if clamping was needed."""
    if 0.0 <= value <= 1.0:
        return value
    clamped = max(0.0, min(1.0, value))
    if warn_if_clamped:
        logger.warning(
            "Confidence value %r is outside [0.0, 1.0]; clamped to %r", value, clamped
        )
    return clamped


def compute_coverage(
    pool: Iterable,
    adapters: list,
    ran_set: dict,
    *,
    run_id: str = "",
    module: str = "",
) -> CoverageReport:
    """Compute coverage from the final pool state.

    Args:
        pool: iterable of entities with a `.type` attribute.
        adapters: list of adapter objects with `.adapter_id` and `.produces` attributes.
        ran_set: dict mapping adapter_id -> "ran" | "skipped" | "failed".
        run_id: run identifier for the report.
        module: caller module name for the report.

    Returns a CoverageReport. Never raises.
    """
    if not adapters:
        return CoverageReport(
            run_id=run_id,
            module=module,
            adapters_registered=0,
            adapters_run=0,
            adapters_skipped=0,
            adapters_failed=0,
            entity_types_expected=set(),
            entity_types_discovered=set(),
            coverage_ratio=1.0,
            per_adapter_coverage={},
            generated_at=datetime.now(timezone.utc),
        )

    entity_types_expected: set = set()
    for a in adapters:
        entity_types_expected.update(getattr(a, "produces", []))

    entity_types_discovered: set = set()
    for entity in pool:
        entity_types_discovered.add(entity.type)

    adapters_run = sum(1 for s in ran_set.values() if s == "ran")
    adapters_skipped = sum(1 for s in ran_set.values() if s == "skipped")
    adapters_failed = sum(1 for s in ran_set.values() if s == "failed")

    if entity_types_expected:
        found = len(entity_types_discovered & entity_types_expected)
        coverage_ratio = found / len(entity_types_expected)
    else:
        coverage_ratio = 1.0

    per_adapter_coverage: dict = {}
    for a in adapters:
        adapter_id = a.adapter_id
        if ran_set.get(adapter_id) == "skipped":
            continue
        produces = set(getattr(a, "produces", []))
        if not produces:
            per_adapter_coverage[adapter_id] = 0.0
            continue
        found_for_adapter = sum(1 for t in produces if t in entity_types_discovered)
        per_adapter_coverage[adapter_id] = found_for_adapter / len(produces)

    return CoverageReport(
        run_id=run_id,
        module=module,
        adapters_registered=len(adapters),
        adapters_run=adapters_run,
        adapters_skipped=adapters_skipped,
        adapters_failed=adapters_failed,
        entity_types_expected=entity_types_expected,
        entity_types_discovered=entity_types_discovered,
        coverage_ratio=coverage_ratio,
        per_adapter_coverage=per_adapter_coverage,
        generated_at=datetime.now(timezone.utc),
    )
