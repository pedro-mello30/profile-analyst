"""Discovery scheduler: selects which adapters are eligible to run next (spec-0018 §6).

IMPORTANT: This module must remain stdlib-only. It must NOT import from
pipeline.enrichment, pipeline.compliance, pipeline.graph, or any stage module.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryConfig:
    max_depth: int = 2
    max_adapters: int = 10
    max_timeout_s: float = 30.0
    max_accounts: int = 50
    allow_noncompliant: bool = False


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

# Statuses that count as "already handled" — adapter will not run again.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"ran", "skipped", "failed"})


def next_runnable(
    adapters: list,
    pool_entity_types: set[str],
    ran_set: dict[str, str],
    config: DiscoveryConfig,
) -> list:
    """Return adapters eligible to run, sorted by priority (ascending).

    An adapter is eligible when ALL of the following hold:

    1. Every entity type in ``adapter.requires`` is present in
       ``pool_entity_types`` (all preconditions are satisfied).
    2. The adapter's ``adapter_id`` is NOT in ``ran_set`` with a terminal
       status (``"ran"``, ``"skipped"``, or ``"failed"``).
    3. ``adapter.tos_compliant`` is ``True``, unless
       ``config.allow_noncompliant`` is ``True``.

    Parameters
    ----------
    adapters:
        All registered adapters (any duck-typed object with ``adapter_id``,
        ``requires``, ``priority``, and ``tos_compliant`` attributes).
    pool_entity_types:
        Set of entity type strings currently available in the account pool.
    ran_set:
        Mapping of ``adapter_id`` → status string for adapters that have
        already been attempted this run.
    config:
        Runtime discovery configuration.

    Returns
    -------
    list
        Eligible adapters sorted by ``priority`` ascending (lowest number =
        highest priority runs first).
    """
    eligible = []
    for adapter in adapters:
        # 1. ToS compliance gate
        if not adapter.tos_compliant and not config.allow_noncompliant:
            continue

        # 2. Already in ran_set with a terminal status
        status = ran_set.get(adapter.adapter_id)
        if status in _TERMINAL_STATUSES:
            continue

        # 3. All required entity types must be satisfied
        if not set(adapter.requires).issubset(pool_entity_types):
            continue

        eligible.append(adapter)

    # Sort by priority ascending (lower number = higher priority = runs first)
    eligible.sort(key=lambda a: a.priority)
    return eligible
