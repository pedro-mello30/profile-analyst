"""Enrichment engine — fixed-point BFS scheduler (spec 0014 §5)."""
from __future__ import annotations

import concurrent.futures
import dataclasses
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline.enrichment.adapter import AdapterConfig, AdapterContext, AdapterResult, EnrichmentAdapter
from pipeline.enrichment.cache import read_cache, write_cache
from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool
from pipeline.governance import (
    AdapterContractError,
    GovernanceReport,
    RateLimitExceeded,
    RateLimiter,
    RobotsPolicy,
    build_report,
    compute_coverage,
    validate_adapter_contract,
)

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    max_depth: int = 2
    max_adapter_runs: int = 20
    max_cost_usd: float = 0.50
    min_confidence_global: float = 0.5
    slow_tier_timeout_s: int = 600
    parallel_workers: int = 8


@dataclass
class EngineState:
    config: EngineConfig
    run_counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    total_runs: int = 0
    total_cost: float = 0.0
    adapter_errors: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    governance_report: GovernanceReport | None = None
    ran_set: dict[str, str] = field(default_factory=dict)


def is_runnable(adapter: EnrichmentAdapter, pool: EntityPool, state: EngineState) -> bool:
    """True if adapter has satisfied requirements, capacity, and resource budget."""
    if not getattr(adapter, "enabled", True):
        return False
    effective_min = max(adapter.min_confidence, state.config.min_confidence_global)
    matching = [
        e for e in pool.by_type_any(adapter.requires)
        if e.confidence >= effective_min and e.depth < state.config.max_depth
    ]
    if not matching:
        return False
    runnable = [
        e for e in matching
        if state.run_counts.get((adapter.adapter_id, e.type, e.value), 0) < adapter.max_instances
    ]
    if not runnable:
        return False
    if state.total_runs >= state.config.max_adapter_runs:
        return False
    if state.total_cost >= state.config.max_cost_usd:
        return False
    return True


def _robots_check_url(adapter: EnrichmentAdapter, trigger_entities: list) -> str:
    """Return a representative URL for the adapter's robots.txt pre-flight check."""
    if url := getattr(adapter, "robots_txt_url", None):
        return url
    for entity in trigger_entities:
        if isinstance(entity.value, str) and entity.value.startswith("http"):
            return entity.value
    return ""


def _signals_to_cache(signals) -> list[dict]:
    result = []
    for s in signals:
        if hasattr(s, "__dict__"):
            result.append(vars(s))
        elif dataclasses.is_dataclass(s):
            result.append(dataclasses.asdict(s))
        else:
            result.append(s)
    return result


def _entities_to_cache(entities) -> list[dict]:
    return [dataclasses.asdict(e) for e in entities]


def _entities_from_cache(raw: list[dict]):
    from pipeline.enrichment.entity import Entity
    result = []
    for d in raw:
        try:
            result.append(Entity(**d))
        except Exception:
            pass
    return result


def _run_with_cache(
    adapter: EnrichmentAdapter,
    pool: EntityPool,
    state: EngineState,
    config: AdapterConfig,
    cache_dir: Path,
    robots_policy: RobotsPolicy,
    rate_limiter: RateLimiter,
) -> AdapterResult:
    """Run adapter or return cached result. Enforces governance pre-flight for live runs."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    effective_min = max(adapter.min_confidence, state.config.min_confidence_global)

    trigger_entities = [
        e for e in pool.by_type_any(adapter.requires)
        if e.confidence >= effective_min
        and e.depth < state.config.max_depth
        and state.run_counts.get((adapter.adapter_id, e.type, e.value), 0) < adapter.max_instances
    ]
    if not trigger_entities:
        return AdapterResult(adapter_id=adapter.adapter_id, entities=[], signals=[],
                             error="no trigger entities", cached=False,
                             ran_at=now, cost_usd=0.0, duration_s=0.0)

    # ── Cache check (governance not needed for cache hits) ─────────────────
    if config.cache_enabled and adapter.ttl_hours > 0:
        for entity in trigger_entities:
            cached = read_cache(cache_dir, adapter.adapter_id, entity.type, entity.value)
            if cached is not None:
                logger.debug("Cache HIT: %s/%s=%s", adapter.adapter_id, entity.type, entity.value)
                state.run_counts[(adapter.adapter_id, entity.type, entity.value)] = \
                    state.run_counts.get((adapter.adapter_id, entity.type, entity.value), 0) + 1
                return AdapterResult(
                    adapter_id=adapter.adapter_id,
                    entities=_entities_from_cache(cached.get("entities_raw", [])),
                    signals=cached.get("signals_raw", []),
                    error=None, cached=True, ran_at=now, cost_usd=0.0, duration_s=0.0,
                )

    # ── Governance pre-flight (live runs only) ─────────────────────────────
    gov = state.governance_report
    check_url = _robots_check_url(adapter, trigger_entities)
    decision = robots_policy.check(check_url, adapter, gov)
    if not decision.allowed:
        logger.warning("Adapter %s skipped by robots.txt: %s", adapter.adapter_id, decision.reason)
        state.ran_set[adapter.adapter_id] = "skipped"
        return AdapterResult(adapter_id=adapter.adapter_id, entities=[], signals=[],
                             error=f"robots.txt denied: {decision.reason}",
                             cached=False, ran_at=now, cost_usd=0.0, duration_s=0.0)

    try:
        rate_limiter.acquire(adapter, gov)
    except RateLimitExceeded as exc:
        logger.warning("Adapter %s rate limit exceeded: %s", adapter.adapter_id, exc)
        state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": str(exc), "at": now})
        state.ran_set[adapter.adapter_id] = "failed"
        return AdapterResult(adapter_id=adapter.adapter_id, entities=[], signals=[],
                             error=str(exc), cached=False, ran_at=now, cost_usd=0.0, duration_s=0.0)

    # ── Live run ───────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        result = adapter.run(trigger_entities, config)
        result.duration_s = time.monotonic() - t0
    except Exception as exc:
        duration = time.monotonic() - t0
        logger.error("Adapter %s raised: %s", adapter.adapter_id, exc)
        state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": str(exc), "at": now})
        state.ran_set[adapter.adapter_id] = "failed"
        return AdapterResult(adapter_id=adapter.adapter_id, entities=[], signals=[],
                             error=str(exc), cached=False, ran_at=now,
                             cost_usd=0.0, duration_s=duration)

    for entity in trigger_entities:
        state.run_counts[(adapter.adapter_id, entity.type, entity.value)] = \
            state.run_counts.get((adapter.adapter_id, entity.type, entity.value), 0) + 1
    state.total_runs += 1
    state.total_cost += result.cost_usd
    state.ran_set[adapter.adapter_id] = "ran"

    if result.error is None and adapter.ttl_hours > 0 and config.cache_enabled:
        for entity in trigger_entities:
            write_cache(
                cache_dir, adapter.adapter_id, entity.type, entity.value,
                {
                    "signals_raw": _signals_to_cache(result.signals),
                    "entities_raw": _entities_to_cache(result.entities),
                },
                ttl_hours=adapter.ttl_hours,
            )
    return result


def _merge_result(result: AdapterResult, pool: EntityPool, state: EngineState) -> list:
    """Merge entities from result into pool. Returns list of newly added/updated entities."""
    new_entities = []
    for entity in result.entities:
        changed = pool.add(entity)
        if changed:
            new_entities.append(entity)
        else:
            existing = pool.get(entity.type, entity.value)
            if existing and existing.source != entity.source:
                state.conflicts.append({
                    "entity_type": entity.type,
                    "entity_value": entity.value,
                    "kept_source": existing.source,
                    "discarded_source": entity.source,
                })
    return new_entities


def _run_parallel(
    adapters: list[EnrichmentAdapter],
    pool: EntityPool,
    state: EngineState,
    config: AdapterConfig,
    cache_dir: Path,
    executor: concurrent.futures.ThreadPoolExecutor,
    robots_policy: RobotsPolicy,
    rate_limiter: RateLimiter,
    timeout: float | None = None,
) -> list[AdapterResult]:
    """Submit adapters to executor, wait for completion. Returns all results."""
    if not adapters:
        return []
    futures = {
        executor.submit(
            _run_with_cache, a, pool, state, config, cache_dir,
            robots_policy, rate_limiter,
        ): a
        for a in adapters
    }
    done, _ = concurrent.futures.wait(
        futures.keys(),
        timeout=timeout,
        return_when=concurrent.futures.ALL_COMPLETED,
    )
    results = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for future, adapter in futures.items():
        if future in done:
            try:
                results.append(future.result())
            except Exception as exc:
                logger.error("Future for %s raised: %s", adapter.adapter_id, exc)
                state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": str(exc)})
                state.ran_set[adapter.adapter_id] = "failed"
        else:
            logger.warning("Adapter %s timed out", adapter.adapter_id)
            state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": "timeout"})
            state.ran_set[adapter.adapter_id] = "failed"
    return results


def run_engine(
    seed_data: dict,
    adapters: list[EnrichmentAdapter],
    config: EngineConfig,
    cache_dir: Path,
    run_id: str | None = None,
    raw_media: list[dict] | None = None,
    source_platform: str = "instagram",
) -> tuple[EntityPool, EngineState, list[AdapterResult]]:
    """Execute the full enrichment scheduling loop. Returns (pool, state, all_results).

    Governance report is available at state.governance_report after return.
    """
    run_id = run_id or str(uuid.uuid4())
    state = EngineState(config=config)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Governance setup ───────────────────────────────────────────────────
    gov_report = build_report(run_id, module="enrichment_engine")
    state.governance_report = gov_report
    robots_policy = RobotsPolicy()
    rate_limiter = RateLimiter()

    # ── Contract validation — filter non-compliant adapters before any run ─
    valid_adapters: list[EnrichmentAdapter] = []
    for adapter in adapters:
        try:
            validate_adapter_contract(adapter)
            valid_adapters.append(adapter)
        except AdapterContractError as exc:
            logger.error(
                "Adapter %s failed contract validation and will not run: %s",
                adapter.adapter_id, exc,
            )
            state.adapter_errors.append({
                "adapter_id": adapter.adapter_id, "error": str(exc), "at": now,
            })
            state.ran_set[adapter.adapter_id] = "failed"

    pool = EntityPool()
    all_results: list[AdapterResult] = []

    adapter_cfg = AdapterConfig(
        profile_id=seed_data.get("handle", "unknown"),
        run_id=run_id,
        max_depth=config.max_depth,
        max_cost_usd=config.max_cost_usd,
        max_runtime_s=config.slow_tier_timeout_s,
        secrets={k: os.environ.get(k, "")
                 for a in valid_adapters
                 for k in getattr(a, "secrets_required", [])},
        osint_enabled=True,
        cache_enabled=True,
        dry_run=False,
        context=AdapterContext(
            raw_profile=seed_data,
            raw_media=raw_media,
            source_platform=source_platform,
        ),
    )

    # ── Seed extraction ────────────────────────────────────────────────────
    for entity_type, data_key in [("handle", "handle"), ("display_name", "display_name"),
                                  ("bio_url", "website")]:
        raw = seed_data.get(data_key)
        if raw:
            try:
                pool.add(make_entity(entity_type, str(raw), source="seed",
                                     confidence=1.0, depth=0, discovered_at=now))
            except Exception as exc:
                logger.debug("Seed extraction failed for %s=%r: %s", entity_type, raw, exc)

    # ── Phase 0: Tier 0 / seed (sequential) ───────────────────────────────
    tier0 = sorted([a for a in valid_adapters if a.tier == "seed"], key=lambda a: a.priority)
    for adapter in tier0:
        if is_runnable(adapter, pool, state):
            result = _run_with_cache(
                adapter, pool, state, adapter_cfg, cache_dir, robots_policy, rate_limiter,
            )
            _merge_result(result, pool, state)
            all_results.append(result)

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
        # ── Phase 1: Fast tier ─────────────────────────────────────────────
        fast = sorted([a for a in valid_adapters if a.tier == "fast"], key=lambda a: a.priority)
        runnable_fast = [a for a in fast if is_runnable(a, pool, state)]
        results = _run_parallel(
            runnable_fast, pool, state, adapter_cfg, cache_dir, ex, robots_policy, rate_limiter,
        )
        for r in results:
            _merge_result(r, pool, state)
        all_results.extend(results)

        # ── Phase 2: Medium tier ───────────────────────────────────────────
        medium = sorted([a for a in valid_adapters if a.tier == "medium"], key=lambda a: a.priority)
        runnable_medium = [a for a in medium if is_runnable(a, pool, state)]
        results = _run_parallel(
            runnable_medium, pool, state, adapter_cfg, cache_dir, ex, robots_policy, rate_limiter,
        )
        for r in results:
            _merge_result(r, pool, state)
        all_results.extend(results)

        # ── Phase 3: Slow tier (wall-clock bounded) ────────────────────────
        slow = sorted([a for a in valid_adapters if a.tier == "slow"], key=lambda a: a.priority)
        deadline = time.monotonic() + config.slow_tier_timeout_s
        while True:
            remaining_budget = max(0.0, deadline - time.monotonic())
            if remaining_budget <= 0:
                break
            runnable_slow = [a for a in slow if is_runnable(a, pool, state)]
            newly_unlocked = [
                a for a in valid_adapters
                if a.tier in ("fast", "medium") and is_runnable(a, pool, state)
            ]
            to_run = runnable_slow + newly_unlocked
            if not to_run:
                break
            results = _run_parallel(
                to_run, pool, state, adapter_cfg, cache_dir, ex, robots_policy, rate_limiter,
                timeout=remaining_budget,
            )
            new_entities = []
            for r in results:
                new_entities.extend(_merge_result(r, pool, state))
            all_results.extend(results)
            if not new_entities:
                break

    # ── Governance report finalisation ─────────────────────────────────────
    gov_report.coverage = compute_coverage(
        pool.all_entities(), valid_adapters, state.ran_set,
        run_id=run_id, module="enrichment_engine",
    )
    gov_report.completed_at = datetime.now(timezone.utc)

    return pool, state, all_results
