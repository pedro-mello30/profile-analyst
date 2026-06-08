"""Fixed-point discovery engine with governance pre-flight (spec-0018 §6)."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.scheduler import DiscoveryConfig, next_runnable
from pipeline.governance import (
    AdapterContractError,
    GovernanceReport,
    RateLimitExceeded,
    RateLimiter,
    RobotsPolicy,
    build_report,
    compute_coverage,
    validate_discovery_adapter_contract,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryEngineState:
    total_adapter_runs: int = 0
    limit_reached: bool = False
    adapter_errors: list[dict] = field(default_factory=list)
    ran_set: dict[str, str] = field(default_factory=dict)
    governance_report: GovernanceReport | None = None


def _entity_type(entity) -> str | None:
    """Duck-typed entity type extraction: try .type attr then .get('type')."""
    t = getattr(entity, "type", None)
    if t is not None:
        return t
    if callable(getattr(entity, "get", None)):
        return entity.get("type")
    return None


class DiscoveryEngine:
    """Fixed-point discovery engine with governance pre-flight (spec-0018 §6)."""

    def __init__(self, adapters: list, config: DiscoveryConfig) -> None:
        self._adapters = adapters
        self._config = config
        self._robots_policy = RobotsPolicy()
        self._rate_limiter = RateLimiter()

    def run(
        self,
        pool: AccountPool,
        seed_entities: list,
        state: DiscoveryEngineState,
        run_id: str = "",
    ) -> None:
        config = self._config

        # 1. Build governance report
        effective_run_id = run_id or str(uuid.uuid4())
        gov_report = build_report(effective_run_id, module="account_discovery")
        state.governance_report = gov_report

        # 2. Validate all adapters — invalid ones go to adapter_errors and ran_set
        valid_adapters: list = []
        for adapter in self._adapters:
            adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))
            try:
                validate_discovery_adapter_contract(adapter)
                valid_adapters.append(adapter)
            except AdapterContractError as exc:
                logger.warning("Invalid adapter %r: %s", adapter_id, exc)
                state.adapter_errors.append({
                    "adapter_id": adapter_id,
                    "error": str(exc),
                })
                state.ran_set[adapter_id] = "failed"

        # 3. Build initial pool_entity_types from seed_entities
        pool_entity_types: set[str] = set()
        for entity in seed_entities:
            t = _entity_type(entity)
            if t:
                pool_entity_types.add(t)

        # 4. Fixed-point loop
        start_time = time.monotonic()

        while True:
            # Check deadline
            elapsed = time.monotonic() - start_time
            if elapsed >= config.max_timeout_s:
                logger.info("Discovery timeout reached (%.2fs)", elapsed)
                state.limit_reached = True
                break

            # Check max_adapters limit
            if state.total_adapter_runs >= config.max_adapters:
                logger.info("max_adapters limit reached (%d)", config.max_adapters)
                state.limit_reached = True
                break

            # Check max_accounts limit
            if len(pool) >= config.max_accounts:
                logger.info("max_accounts limit reached (%d)", config.max_accounts)
                state.limit_reached = True
                break

            # Get next runnable adapters
            runnable = next_runnable(valid_adapters, pool_entity_types, state.ran_set, config)
            if not runnable:
                logger.debug("Fixed point reached — no more runnable adapters")
                break

            new_accounts_this_round = 0

            for adapter in runnable:
                adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))

                # Re-check limits mid-round
                elapsed = time.monotonic() - start_time
                if elapsed >= config.max_timeout_s:
                    state.limit_reached = True
                    break
                if state.total_adapter_runs >= config.max_adapters:
                    state.limit_reached = True
                    break
                if len(pool) >= config.max_accounts:
                    state.limit_reached = True
                    break

                # Robots policy check
                check_url = getattr(adapter, "robots_txt_url", "")
                decision = self._robots_policy.check(check_url, adapter, gov_report)
                if not decision.allowed:
                    logger.info(
                        "Adapter %r blocked by robots policy: %s", adapter_id, decision.reason
                    )
                    state.ran_set[adapter_id] = "skipped"
                    continue

                # Rate limiter
                try:
                    self._rate_limiter.acquire(adapter, gov_report)
                except RateLimitExceeded as exc:
                    logger.warning("Adapter %r rate-limited: %s", adapter_id, exc)
                    state.adapter_errors.append({
                        "adapter_id": adapter_id,
                        "error": str(exc),
                    })
                    state.ran_set[adapter_id] = "failed"
                    continue

                # Run adapter
                try:
                    discovered = adapter.run(seed_entities, config)
                    state.ran_set[adapter_id] = "ran"
                    state.total_adapter_runs += 1

                    for account in (discovered or []):
                        changed = pool.add(account)
                        if changed:
                            new_accounts_this_round += 1
                            # Add platform-derived entity types
                            platform_lower = account.platform.lower()
                            pool_entity_types.add(platform_lower)
                            pool_entity_types.add(f"{platform_lower}_handle")

                except Exception as exc:
                    logger.exception("Adapter %r raised unexpectedly: %s", adapter_id, exc)
                    state.adapter_errors.append({
                        "adapter_id": adapter_id,
                        "error": str(exc),
                    })
                    state.ran_set[adapter_id] = "failed"

            # If limit was set mid-round, stop outer loop too
            if state.limit_reached:
                break

            # Fixed-point: no new accounts discovered this round
            if new_accounts_this_round == 0:
                logger.debug("Fixed point reached — zero new accounts this round")
                break

        # 5. Finalise: add all current pool entity types
        for account in pool.all_accounts():
            platform_lower = account.platform.lower()
            pool_entity_types.add(platform_lower)
            pool_entity_types.add(f"{platform_lower}_handle")

        # Build lightweight wrappers so compute_coverage can iterate .type attributes.
        # DiscoveredAccount has no .type; pool_entity_types tracks all types seen this run.
        class _PoolEntity:
            __slots__ = ("type",)
            def __init__(self, t: str) -> None:
                self.type = t

        gov_report.coverage = compute_coverage(
            [_PoolEntity(t) for t in pool_entity_types],
            valid_adapters,
            state.ran_set,
            run_id=effective_run_id,
            module="account_discovery",
        )

        gov_report.completed_at = datetime.now(timezone.utc)
