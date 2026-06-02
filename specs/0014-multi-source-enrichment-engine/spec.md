# Spec 0014 — Multi-Source Enrichment Engine: Dependency-Driven Cross-Platform Profile Enrichment

Status: draft · Date: 2026-06-02 · Method: Spec-Driven Development

---

## 0. Philosophy (SDD)

This spec describes **what** and **why**, separated from **how**. Each section defines:

1. **Intent** — purpose of the component.
2. **Inputs** — format and expected structure.
3. **Outputs** — format and structure produced.
4. **Invariants** — rules that may never be violated.
5. **Failure modes** — what counts as failure; what the component does NOT do.

The implementation lives in `pipeline/enrichment/`; this spec is the source of truth. No adapter
or engine change is valid without a corresponding spec section that justifies it.

---

## 1. Problem

The current pipeline (Stages 1–6) produces a dossier seeded exclusively from Instagram data via
Apify. This yields a thin profile: a tier label, a single niche, an engagement rate, and a few
computed scores. A real creator leaves dozens of signals across the open web — podcast feeds,
YouTube channels, newsletters, press coverage, public business registrations, cross-platform
accounts, and knowledge graph entries — that the current pipeline ignores entirely.

Concrete gaps:

- A creator's bio link (`linktr.ee/...`) expands to 6–12 additional platforms; we never parse it.
- Podcast presence (iTunes, Spotify) is never queried even when the bio mentions one.
- Google Knowledge Graph and Wikidata contain structured facts about notable creators that go
  completely unused.
- Username enumeration across 3,000+ sites (Maigret) can discover TikTok, YouTube, LinkedIn, and
  GitHub accounts automatically.
- OSINT communication tools (Holehe, GHunt) can map a discovered email to 120+ registered
  services, revealing the creator's full digital footprint.
- GDELT and Google News RSS provide press coverage signals absent from social metrics entirely.
- Brazilian business registrations (CNPJ/ReceitaWS) reveal whether a creator operates a legal
  entity — critical for B2B brand partnerships.

The root cause is architectural: Stage 1 is a single, static adapter. There is no mechanism to
fan out across heterogeneous sources, chain discoveries together, or express the dependency
between a discovered entity and the adapter that consumes it.

---

## 2. Goals / Non-Goals

### Goals

- An **Enrichment Engine** that receives a seed profile (Stage 2 output) and fans out across all
  configured source adapters in dependency order, returning a structured `enrichment_map.json`.
- A **dependency graph model**: each adapter declares `requires` (entity types it needs) and
  `produces` (entity types it emits); the engine resolves execution order automatically.
- A **fixed-point scheduling loop** that re-evaluates runnable adapters after every new entity
  is discovered, until no new work exists or resource limits are reached.
- A **three-tier execution model**: Tier 0 (seed enrichment, ~5s), Fast Tier (~30s, blocks
  dossier v1), Medium/Slow Tiers (async, update dossier v2/v3).
- A **per-adapter cache layer** keyed by `(adapter_id, entity_type, entity_value)` with
  configurable TTL — prevents quota exhaustion on re-runs.
- **Hard resource limits** per profile run: `max_depth`, `max_adapter_runs`, `max_cost_usd`.
- Full **compliance coverage** for OSINT sources: every enrichment entity carries provenance,
  confidence, and an `osint_risk` flag for sources that may reveal sensitive personal data.
- **Integration into the existing pipeline** as a new Stage 1B, sitting between Stage 1
  (Instagram ingest) and Stage 2 (normalize), consuming Stage 2 output and writing
  `enrichment_map.json` before Stage 3 LLM features.

### Non-Goals

| Out of scope | Reason | Target |
|---|---|---|
| Real-time streaming enrichment | Batch per-profile is sufficient for v1 | future |
| Paid data providers (Modash, HypeAuditor, Clearbit) | Free sources cover the required signal | future |
| Authenticated scraping of private profiles | Legal risk; not within ToS of target platforms | never |
| Storing raw OSINT artifacts (screenshots, cached HTML) | Data minimization; enrichment_map stores structured signals only | design |
| Graph traversal of follower networks | Covered by spec 0012 (association graph) | done |
| Real-time webhook push for v2/v3 dossier | Phase 2 — v1 uses polling via `enrichment_status.json` | future |

---

## 3. Entity Model

An **Entity** is a typed, valued piece of information discovered during enrichment. Entities are
the connective tissue of the dependency graph — adapters consume entity types and produce entity
types. All values are stored in **canonical normalized form** (see §3.1) so that the same real-world
identifier is never treated as two distinct entities due to formatting differences.

### 3.0 Entity Dataclass

```python
@dataclass(frozen=True)
class Entity:
    type: str           # canonical type from ENTITY_TYPES registry (§3.1); validated on construction
    value: str          # normalized string value — apply EntityTypeSpec.normalizer before constructing
    source: str         # adapter_id that produced this entity
    confidence: float   # 0.0–1.0; clamped with a warning if out of range on construction
    depth: int          # hops from seed; depth=0 reserved for seed entities
    discovered_at: str  # UTC ISO 8601 timestamp: "2026-06-02T21:00:00Z"

    def __post_init__(self):
        if self.type not in ENTITY_TYPES:
            raise InvalidEntityTypeError(f"Unknown entity type: {self.type!r}")
        if not (0.0 <= self.confidence <= 1.0):
            # Clamp silently — adapters may emit un-clamped floats from raw API responses
            object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))
        if self.depth < 0:
            raise ValueError(f"depth must be >= 0, got {self.depth}")
        try:
            datetime.fromisoformat(self.discovered_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"discovered_at must be UTC ISO 8601, got {self.discovered_at!r}")
        # Enforce normalization: value must already be in canonical form
        spec = ENTITY_TYPES[self.type]
        normalized = spec.normalizer(self.value)
        if normalized != self.value:
            raise ValueError(
                f"Entity value {self.value!r} is not normalized for type {self.type!r}. "
                f"Expected {normalized!r}. Apply EntityTypeSpec.normalizer before constructing."
            )
```

### 3.1 Canonical Entity Type Registry

Each entry in `ENTITY_TYPES` is an `EntityTypeSpec` — a value specification that enforces what an
entity value must look like and how to normalize raw input into canonical form.

```python
@dataclass(frozen=True)
class EntityTypeSpec:
    name: str
    pattern: re.Pattern        # value must match after normalization
    normalizer: Callable[[str], str]  # call this on raw input before constructing Entity
    example: str               # used in tests and documentation
    osint_risk: bool           # True if this type may contain sensitive PII
    produced_by: tuple[str, ...] = ()
    consumed_by: tuple[str, ...] = ()
```

**Normalization rules per type** (applied by calling `ENTITY_TYPES[type].normalizer(raw_value)`):

| Type | Normalization | Pattern | `osint_risk` |
|---|---|---|---|
| `handle` | lowercase; strip leading `@` or `u/` | `^[a-z0-9._]{1,64}$` | false |
| `display_name` | strip whitespace | `^.+$` | false |
| `bio_url` | lowercase scheme+host; strip trailing `/` | `^https?://.+$` | false |
| `email` | full lowercase | `^[^@]+@[^@]+\.[^@]+$` | **true** |
| `gmail` | full lowercase; must end `@gmail.com` | `^[^@]+@gmail\.com$` | **true** |
| `domain` | full lowercase; strip `www.` prefix | `^[a-z0-9.-]+\.[a-z]{2,}$` | false |
| `subdomain` | full lowercase | `^[a-z0-9.-]+\.[a-z0-9.-]+\.[a-z]{2,}$` | false |
| `youtube_channel_id` | strip whitespace; keep `UC`-prefix | `^UC[a-zA-Z0-9_-]{22}$` | false |
| `youtube_handle` | lowercase; ensure `@` prefix | `^@[a-zA-Z0-9._-]{3,30}$` | false |
| `tiktok_handle` | lowercase; strip `@` then re-add | `^@[a-zA-Z0-9._]{1,24}$` | false |
| `twitter_handle` | lowercase; strip `@` then re-add | `^@[a-zA-Z0-9_]{1,15}$` | false |
| `instagram_handle` | lowercase; strip `@` | `^[a-z0-9._]{1,30}$` | false |
| `linkedin_url` | lowercase; canonical `linkedin.com/in/{slug}/` | `^https://[a-z.]*linkedin\.com/in/[^/]+/?$` | false |
| `github_handle` | lowercase | `^[a-z0-9-]{1,39}$` | false |
| `reddit_username` | lowercase; strip `u/` | `^[a-zA-Z0-9_-]{3,20}$` | false |
| `twitch_handle` | lowercase | `^[a-z0-9_]{4,25}$` | false |
| `spotify_artist_id` | ensure `spotify:artist:` prefix | `^spotify:artist:[a-zA-Z0-9]+$` | false |
| `podcast_url` | lowercase scheme+host; strip trailing `/` | `^https?://.+$` | false |
| `podcast_itunes_id` | strip whitespace | `^\d{6,12}$` | false |
| `substack_url` | lowercase | `^https://[a-z0-9-]+\.substack\.com/?$` | false |
| `website_url` | lowercase scheme+host; strip trailing `/` | `^https?://.+$` | false |
| `wikidata_id` | uppercase | `^Q\d+$` | false |
| `cnpj` | strip all non-digits; keep 14 digits | `^\d{14}$` | **true** |
| `phone` | E.164: `+` then digits; strip spaces | `^\+\d{10,15}$` | **true** |

**Produced-by / consumed-by cross-reference:**

| Type | Produced by | Consumed by |
|---|---|---|
| `handle` | seed | Maigret, Reddit, GitHub, Twitch |
| `display_name` | seed | KnowledgeGraph, GDELT, iTunes, Wikidata |
| `bio_url` | seed | Linktree |
| `email` | Linktree, website_scrape | Holehe, GHunt, HIBP |
| `gmail` | Holehe | GHunt |
| `domain` | Linktree, WHOIS, crt | WHOIS, crt, website_scrape |
| `subdomain` | crt | website_scrape |
| `youtube_channel_id` | Linktree, Maigret, GHunt | YouTube |
| `youtube_handle` | Linktree, Maigret | YouTube |
| `tiktok_handle` | Maigret, Linktree | TikTok |
| `twitter_handle` | Maigret, Linktree | Twitter |
| `instagram_handle` | Maigret, Linktree | (already ingested — no downstream adapter) |
| `linkedin_url` | Maigret, Linktree | LinkedIn |
| `github_handle` | Maigret, Linktree | GitHub |
| `reddit_username` | Maigret | Reddit |
| `twitch_handle` | Maigret, Linktree | Twitch |
| `spotify_artist_id` | Linktree, Spotify | Spotify |
| `podcast_url` | Linktree, bio | iTunes, Spotify |
| `podcast_itunes_id` | iTunes | iTunes |
| `substack_url` | Linktree, Maigret | Substack |
| `website_url` | Linktree, WHOIS | website_scrape, WHOIS |
| `wikidata_id` | KnowledgeGraph, Wikidata | Wikidata |
| `cnpj` | website_scrape, bio | CNPJ |
| `phone` | Linktree, website_scrape | PhoneInfo |

### 3.2 Entity Pool

The engine maintains a single thread-safe `EntityPool` per profile run. All adapter threads share
one pool; concurrent writes are serialized with an internal lock.

```python
class EntityPool:
    """Thread-safe entity store. Key = (type, value); higher confidence wins on conflict."""

    def __init__(self):
        self._store: dict[tuple[str, str], Entity] = {}
        self._provenance: dict[tuple[str, str], list[str]] = {}  # all sources per entity
        self._lock = threading.Lock()

    def add(self, entity: Entity, input_depths: list[int] | None = None) -> bool:
        """Insert or update the pool. Returns True if the pool changed.

        `input_depths` — depths of the entities that triggered this adapter run.
        Required for depth > 0 entities (used to verify §3.3 depth invariant).
        """
        key = (entity.type, entity.value)
        with self._lock:
            self._provenance.setdefault(key, []).append(entity.source)
            existing = self._store.get(key)
            if existing is None or entity.confidence > existing.confidence:
                self._store[key] = entity
                return True
            return False

    def get(self, entity_type: str, entity_value: str) -> Entity | None:
        key = (entity_type, entity_value)
        with self._lock:
            return self._store.get(key)

    def by_type(self, entity_type: str) -> list[Entity]:
        with self._lock:
            return [e for e in self._store.values() if e.type == entity_type]

    def provenance(self, entity_type: str, entity_value: str) -> list[str]:
        """All adapter_ids that contributed to this entity."""
        with self._lock:
            return list(self._provenance.get((entity_type, entity_value), []))

    def snapshot(self) -> list[dict]:
        """JSON-serializable list of all entities, suitable for enrichment_map.json."""
        with self._lock:
            return [
                {**vars(e), "all_sources": self._provenance.get((e.type, e.value), [])}
                for e in self._store.values()
            ]
```

Seed entities (`handle`, `display_name`, `bio_url`) are inserted at `depth=0, confidence=1.0`
before the scheduling loop begins. Seeds are the only entities that may have `depth=0`.

### 3.3 Invariants

- **Depth rule:** An entity produced by an adapter whose input seeds have depths `d₁, d₂, …`
  must have `depth = max(d₁, d₂, …) + 1`. The engine enforces this when constructing produced
  entities — adapters receive a `depth_for_entity(input_entities)` helper and must use it.
- **Seed exclusivity:** `depth=0` is reserved for entities inserted before the scheduling loop.
  No adapter may emit an entity with `depth=0`; the engine rejects such output with a warning.
- **Deduplication:** Two entities with the same `(type, value)` are the same entity regardless of
  `source` or `depth`. The pool keeps the higher-confidence instance; all contributing sources
  accumulate in `provenance`. The lower-confidence duplicate is discarded, not merged.
- **Normalization contract:** The `value` field of every entity in the pool is guaranteed to be
  in canonical normalized form. Adapters call `ENTITY_TYPES[type].normalizer(raw)` before
  constructing an `Entity`. The `Entity.__post_init__` validates normalization and raises if not met.
- **Type closure:** The set of recognized entity types is fixed at `ENTITY_TYPES`. Adapters
  declaring `produces` entries not in `ENTITY_TYPES` fail validation at registry load time, not
  at run time.

---

## 4. Adapter Contract

### 4.0 AdapterConfig — engine-to-adapter boundary

`AdapterConfig` is passed by the engine to every `run()` call. It represents the full execution
context for a single adapter invocation and is the only mechanism through which adapters receive
secrets, limits, and run identity.

```python
@dataclass(frozen=True)
class AdapterConfig:
    # Run identity
    profile_id: str          # handle being enriched — used for cache key namespacing
    run_id: str              # UUID for this enrichment run — for tracing/logging

    # Resource limits (propagated from EngineConfig)
    max_depth: int
    max_cost_usd: float
    max_runtime_s: int       # wall-clock budget for this adapter invocation

    # Secrets — injected by engine from env; never hardcoded or logged
    secrets: dict[str, str]  # e.g. {"HIBP_API_KEY": "...", "YOUTUBE_API_KEY": "..."}

    # Feature flags
    osint_enabled: bool      # if False, adapters with osint_risk=True must skip
    cache_enabled: bool      # if False, cache is bypassed for this run (--bust-cache)
    dry_run: bool            # if True, adapter must not make live network calls
```

### 4.1 EnrichmentAdapter ABC

Every adapter is a Python class implementing `EnrichmentAdapter`. Validation of all class-level
attributes fires at **import time** via `__init_subclass__` — a mis-configured adapter raises
`AdapterContractError` when its module is loaded, not silently at runtime.

```python
_VALID_TIERS = frozenset({"seed", "fast", "medium", "slow"})
_VALID_GDPR_BASES = frozenset({"LEGITIMATE_INTERESTS", "CONSENT", "NONE"})
_VALID_DATA_CATEGORIES = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})


class EnrichmentAdapter(ABC):
    # Identity
    adapter_id: str          # unique slug: "youtube", "maigret", "holehe"
    display_name: str

    # Dependency graph
    requires: list[str]      # entity types this adapter needs at least one of
    produces: list[str]      # entity types this adapter may emit

    # Scheduling
    tier: str                # one of _VALID_TIERS
    priority: int            # lower = runs first within a tier

    # Resource
    cost_usd: float          # estimated per-run cost (0.0 for free sources)
    timeout_s: int           # hard timeout; adapter returns partial or empty on breach
    retry_max: int
    rate_limit_rpm: int      # max requests per minute to the upstream source (0 = unlimited)

    # Cache
    ttl_hours: int           # 0 = no cache

    # Safety
    min_confidence: float    # skip if triggering entity.confidence < this (0.0–1.0)
    max_instances: int       # max times this adapter runs per profile (prevents loops)
    osint_risk: bool         # True for adapters that may surface sensitive personal data
    secrets_required: list[str]  # env var names the adapter needs (e.g. ["HIBP_API_KEY"])

    # Compliance
    gdpr_basis: str          # one of _VALID_GDPR_BASES
    data_category: str       # one of _VALID_DATA_CATEGORIES
    tos_compliant: bool

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if ABC in cls.__bases__:
            return  # skip validation for the ABC itself
        errors = []
        for attr in ("adapter_id", "display_name", "requires", "produces", "tier",
                     "priority", "cost_usd", "timeout_s", "retry_max", "rate_limit_rpm",
                     "ttl_hours", "min_confidence", "max_instances", "osint_risk",
                     "secrets_required", "gdpr_basis", "data_category", "tos_compliant"):
            if not hasattr(cls, attr):
                errors.append(f"missing required class attribute: {attr!r}")
        if hasattr(cls, "tier") and cls.tier not in _VALID_TIERS:
            errors.append(f"tier={cls.tier!r} not in {_VALID_TIERS}")
        if hasattr(cls, "gdpr_basis") and cls.gdpr_basis not in _VALID_GDPR_BASES:
            errors.append(f"gdpr_basis={cls.gdpr_basis!r} not in {_VALID_GDPR_BASES}")
        if hasattr(cls, "data_category") and cls.data_category not in _VALID_DATA_CATEGORIES:
            errors.append(f"data_category={cls.data_category!r} not in {_VALID_DATA_CATEGORIES}")
        if hasattr(cls, "requires"):
            bad = [t for t in cls.requires if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"requires contains unknown entity types: {bad}")
        if hasattr(cls, "produces"):
            bad = [t for t in cls.produces if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"produces contains unknown entity types: {bad}")
        if hasattr(cls, "min_confidence") and not (0.0 <= cls.min_confidence <= 1.0):
            errors.append(f"min_confidence={cls.min_confidence} out of range [0.0, 1.0]")
        if errors:
            raise AdapterContractError(
                f"Adapter {cls.__name__!r} has {len(errors)} contract violation(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    @abstractmethod
    def run(
        self,
        seed_entities: list[Entity],   # entities of required types, already in pool
        config: AdapterConfig,
    ) -> AdapterResult: ...
```

### 4.2 AdapterResult and Signal

```python
@dataclass
class AdapterResult:
    adapter_id: str
    entities: list[Entity]         # new entities produced; values must be pre-normalized
    signals: list[Signal]          # enrichment signals for dossier (non-entity data)
    error: str | None              # None on success; error message on partial/full failure
    cached: bool                   # True if result came from cache (no live call made)
    ran_at: str                    # UTC ISO timestamp
    cost_usd: float                # actual cost incurred (may differ from estimate)
    duration_s: float              # wall-clock time of the run() call
```

```python
@dataclass
class Signal:
    key: str            # e.g. "youtube_subscriber_count", "press_mention_count"
    value: Any          # int | float | str | list — JSON-serializable
    unit: str | None    # "count" | "percent" | "score_0_1" | None
    confidence: float   # 0.0–1.0
    method: str         # "api" | "scrape" | "osint" | "computed"
    source: str         # adapter_id that produced this signal
    osint_risk: bool    # True if this signal may contain sensitive PII
```

### 4.3 Adapter YAML Configuration

Each adapter is configured at `pipeline/enrichment/config/{adapter_id}.yaml`. Every file is
validated against `pipeline/enrichment/schemas/adapter_config.schema.json` (JSON Schema
draft-2020-12, `additionalProperties: false`) at registry load time. A YAML file whose
`adapter_id` field does not match its filename fails validation immediately.

New optional fields vs. the original spec:

```yaml
adapter_id: youtube
enabled: true
tier: fast
priority: 10
cost_usd: 0.000
timeout_s: 15
retry_max: 2
rate_limit_rpm: 0          # YouTube quota is unit-based, not RPM
ttl_hours: 24
min_confidence: 0.6
max_instances: 3
osint_risk: false
secrets_required: []       # uses YOUTUBE_API_KEY if set; falls back to public quota
gdpr_basis: LEGITIMATE_INTERESTS
data_category: PUBLIC_API
tos_compliant: true
```

```yaml
adapter_id: maigret
enabled: true
tier: slow
priority: 50
cost_usd: 0.000
timeout_s: 300
retry_max: 1
rate_limit_rpm: 0          # self-hosted; no upstream rate limit
ttl_hours: 168
min_confidence: 0.8
max_instances: 1
osint_risk: true
secrets_required: []
gdpr_basis: LEGITIMATE_INTERESTS
data_category: OSINT
tos_compliant: true
```

```yaml
adapter_id: holehe
enabled: true
tier: medium
priority: 20
cost_usd: 0.000
timeout_s: 60
retry_max: 1
rate_limit_rpm: 30         # holehe scans 120+ sites; space calls to avoid triggering blocks
ttl_hours: 72
min_confidence: 0.7
max_instances: 2
osint_risk: true
secrets_required: []       # self-hosted; no API key
gdpr_basis: LEGITIMATE_INTERESTS
data_category: OSINT
tos_compliant: true
```

```yaml
adapter_id: hibp
enabled: true
tier: medium
priority: 30
cost_usd: 0.004
timeout_s: 10
retry_max: 2
rate_limit_rpm: 10         # HIBP enforces strict rate limits per subscription tier
ttl_hours: 168
min_confidence: 0.7
max_instances: 3           # up to 3 emails may be discovered per profile
osint_risk: true
secrets_required:
  - HIBP_API_KEY           # adapter skips (fallback: skip) if this is absent
gdpr_basis: LEGITIMATE_INTERESTS
data_category: OSINT
tos_compliant: true
```

---

## 5. Enrichment Engine

### 5.1 Seed Extraction

Before the scheduling loop, the engine extracts seed entities from `02-normalized.json`:

```
handle       ← normalized["handle"]
display_name ← normalized["display_name"]
bio_url      ← normalized["website"] (if present)
email        ← regex scan of normalized["bio"] for mailto: patterns
```

All seed entities are inserted into the `EntityPool` at `depth=0, confidence=1.0`.

### 5.2 Dependency Resolution

The engine resolves which adapters are *runnable* given the current `EntityPool`:

```python
def is_runnable(adapter: EnrichmentAdapter, pool: EntityPool, state: EngineState) -> bool:
    # 1. Enabled
    if not adapter.enabled:
        return False
    # 2. Has at least one required entity type with sufficient confidence.
    #    Confidence floor = max(adapter floor, global floor) — the stricter of the two.
    #    Bug fixed: min_confidence_global was defined in §5.5 but not enforced here.
    effective_min_confidence = max(adapter.min_confidence, state.config.min_confidence_global)
    matching = [e for e in pool.by_type_any(adapter.requires)
                if e.confidence >= effective_min_confidence
                and e.depth < state.config.max_depth]
    if not matching:
        return False
    # 3. Has not exhausted max_instances for this (adapter, entity) pair.
    #    run_counts tracks both cache hits and live runs — prevents duplicate scheduling.
    runnable_entities = [
        e for e in matching
        if state.run_counts.get((adapter.adapter_id, e.type, e.value), 0) < adapter.max_instances
    ]
    if not runnable_entities:
        return False
    # 4. Resource limits not exceeded
    if state.total_runs >= state.config.max_adapter_runs:
        return False
    if state.total_cost >= state.config.max_cost_usd:
        return False
    return True
```

`run_counts` and `total_runs` are updated differently on cache hit vs live run:

```python
# On CACHE HIT:
state.run_counts[(adapter.adapter_id, entity.type, entity.value)] += 1
# state.total_runs is NOT incremented — cache hits are free against the adapter-run budget
# state.total_cost is NOT incremented

# On LIVE RUN:
state.run_counts[(adapter.adapter_id, entity.type, entity.value)] += 1
state.total_runs += 1
state.total_cost += result.cost_usd
```

### 5.3 Scheduling Algorithm — Fixed-Point BFS

```
INIT:
  pool    ← seed_entities
  pending ← resolve_runnable(all_adapters, pool, state)
  tier_0  ← [a for a in pending if a.tier == "seed"]

PHASE 0 — Seed enrichment (sequential, blocking):
  for adapter in tier_0 (sorted by priority):
    result = run_with_cache(adapter, pool)
    merge new entities into pool
    update state (runs, cost)
  pending ← resolve_runnable(remaining_adapters, pool, state)

PHASE 1 — Fast tier (parallel, blocking — dossier v1 waits):
  fast = [a for a in pending if a.tier == "fast"]
  results = run_parallel(fast, pool, state)
  merge all new entities into pool
  update state
  BUILD DOSSIER v1

PHASE 2 — Medium tier (parallel, async):
  medium = resolve_runnable(remaining, pool, state)
  medium = [a for a in medium if a.tier == "medium"]
  results = run_parallel(medium, pool, state)
  merge new entities
  update state
  BUILD DOSSIER v2

PHASE 3 — Slow tier (parallel, async, wall-clock bounded by slow_tier_timeout_s):
  executor = ThreadPoolExecutor(max_workers=config.parallel_workers)
  deadline  = time.monotonic() + config.slow_tier_timeout_s
  loop:
    slow = resolve_runnable(remaining, pool, state)
    if not slow or time.monotonic() >= deadline:
      break
    futures = {executor.submit(run_with_cache, a, pool): a for a in slow}
    done, _ = concurrent.futures.wait(
        futures,
        timeout=max(0, deadline - time.monotonic()),
        return_when=concurrent.futures.ALL_COMPLETED,
    )
    for future in futures:
      if future in done:
        result = future.result()
        new_entities = merge(result)
      else:
        # Future did not complete before deadline — mark as timed_out
        adapter = futures[future]
        log_timeout(adapter, timed_out=True)
        # timed_out entries: excluded from total_runs and total_cost accounting
    if new_entities:
      # New entities may unlock additional adapters; runs in next loop iteration
      pass
    if no new entities in this iteration and no new unlocked:
      break   ← fixed point
  executor.shutdown(wait=False)  # do not block; in-flight adapters are abandoned
  BUILD DOSSIER v3
```

**Termination is guaranteed** by the combination of:
- `max_depth` — limits how far entity discovery propagates
- `max_adapter_runs` — hard cap on total invocations
- `max_instances` — each (adapter, entity) pair runs at most N times
- Entity deduplication — same `(type, value)` never triggers downstream twice

### 5.3.1 Fallback Semantics

Each adapter declares `fallback: skip | deferred | error`. These have precise meanings:

| `fallback` value | On adapter failure | Written to `adapter_runs[]` |
|---|---|---|
| `skip` | Engine continues; no entities or signals from this adapter | `status: "skipped"`, `error: "<reason>"` |
| `deferred` | Engine emits a placeholder signal `{key: "{adapter_id}_status", value: "deferred"}` in `enrichment_map.json` | `status: "deferred"` |
| `error` | Engine logs the error and continues (does **not** abort the run) | `status: "error"`, `error: "<traceback digest>"` |

No fallback value causes the engine to raise or halt — the engine always completes and always
writes an `enrichment_map.json`, even if every adapter failed.

### 5.3.2 Partial Results

An adapter that times out may return a partial `AdapterResult` with some entities and signals
already collected and `error: "timeout"`. The engine accepts partial results — entities and
signals are merged into the pool. The `adapter_runs[]` entry records `status: "timeout"` alongside
the partial counts (`entities_produced`, `signals_produced`).

An adapter that raises an unhandled exception produces no result — partial in-memory state is
discarded. This is the only case where zero entities are contributed by a run that started.

### 5.3.3 Idempotent Restart

If the engine process is killed mid-run (SIGKILL, OOM), restarting with the same handle resumes
from the cache. Adapters whose results are cached are not re-run. Adapters that were in-flight
at kill time are treated as not-yet-run (their cache entry was never written) and re-scheduled
normally. This means the engine is **exactly-at-least-once**: a killed adapter may run again;
a completed adapter runs exactly once.

### 5.3.4 Worker Pool and Backpressure

`run_parallel(adapters, pool, state)` uses a `ThreadPoolExecutor(max_workers=parallel_workers)`.
When more adapters are runnable than `parallel_workers`, the extras are queued in the executor's
internal queue (unbounded). Rate-limit enforcement (`rate_limit_rpm`) is handled per-adapter
inside `run()` — the engine does not impose inter-adapter global rate limiting.

Discovery feedback (Maigret → new entities → unlock YouTube) is processed only **after the
entire current batch completes** — the engine does not interrupt a running batch to add newly
unlocked work. This simplifies the concurrency model at the cost of one extra scheduling cycle.

### 5.4 Cache Layer

**Cache key function** — must be a named, unit-tested function (not an inlined f-string):

```python
import hashlib

def make_cache_key(adapter_id: str, entity_type: str, entity_value: str) -> str:
    """Return a deterministic hex digest for a (adapter, entity_type, entity_value) triple.

    Unit test: make_cache_key("youtube", "youtube_channel_id", "UCxyz123")
    must equal sha256("youtube:youtube_channel_id:UCxyz123").hexdigest()
    (verified against a known constant in tests/enrichment/test_cache.py).
    """
    raw = f"{adapter_id}:{entity_type}:{entity_value}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

Storage: `projects/{handle}/.enrichment_cache/{make_cache_key(...)}.json`

```json
{
  "key": "sha256:...",
  "adapter_id": "youtube",
  "entity_type": "youtube_channel_id",
  "entity_value": "UCxyz123",
  "result": { ... AdapterResult ... },
  "cached_at": "2026-06-02T21:00:00Z",
  "expires_at": "2026-06-03T21:00:00Z"
}
```

On cache hit: the `AdapterResult` is returned immediately with `cached=true`; the result's
entities are merged into the pool as if the adapter had just run. Cache hits do **not** count
against `max_adapter_runs` but do count as an instance of the adapter having run (preventing
redundant re-scheduling).

### 5.5 Resource Limits

```python
@dataclass
class EngineConfig:
    max_depth: int = 2
    max_adapter_runs: int = 20
    max_cost_usd: float = 0.50
    min_confidence_global: float = 0.5    # floor across all adapters
    slow_tier_timeout_s: int = 600        # wall-clock limit for slow phase
    parallel_workers: int = 8             # max concurrent adapter threads
```

When a limit is reached, the engine emits `limit_reached: true` in `enrichment_status.json` and
builds whatever dossier version is available. It never raises an exception for limit exhaustion.

---

## 6. Source Registry

### 6.1 Tier 0 — Seed Enrichment

#### Linktree / Bio-Link Parser
- **requires:** `bio_url`
- **produces:** `email`, `domain`, `youtube_channel_id`, `youtube_handle`, `tiktok_handle`, `twitter_handle`, `instagram_handle`, `podcast_url`, `substack_url`, `website_url`, `github_handle`, `twitch_handle`, `spotify_artist_id`
- **method:** HTTP GET on bio_url → parse JSON-LD or HTML link list
- **supports:** Linktree, Beacons.ai, Carrd, bio.link, direct personal site
- **cost:** $0 (or Apify $0.001 if JS rendering required)
- **signals emitted:** `bio_link_platform_count`, `bio_link_platforms[]`

#### WHOIS / RDAP
- **requires:** `domain`
- **produces:** `registrant_org`, `domain_age_days`, `subdomain`
- **method:** RDAP (ICANN free) via `rdap.org` REST API
- **cost:** $0
- **signals emitted:** `domain_age_days`, `registrant_country`, `registrar`

#### crt.sh — Certificate Transparency
- **requires:** `domain`
- **produces:** `subdomain`, `alt_domains`
- **method:** `crt.sh` public PostgreSQL API: `https://crt.sh/?q=%.{domain}&output=json`
- **cost:** $0
- **signals emitted:** `cert_count`, `subdomains_found[]`
- **osint_risk:** false (certificates are public infrastructure data)

---

### 6.2 Fast Tier

#### Google Knowledge Graph
- **requires:** `display_name` OR `handle`
- **produces:** `wikidata_id`, `wikipedia_url`
- **method:** Knowledge Graph Search API (`kgsearch.googleapis.com/v1/entities:search`)
- **free tier:** 100,000 queries/day
- **cost:** $0
- **signals emitted:** `kg_entity_found`, `kg_description`, `kg_entity_types[]`, `kg_relevance_score`
- **note:** Returns `@type` array — `Person`, `Organization`, `MusicGroup`, etc.

#### Wikidata SPARQL
- **requires:** `wikidata_id` (from KG) OR `display_name`
- **produces:** (none — terminal)
- **method:** Wikidata SPARQL endpoint (`query.wikidata.org`)
- **free tier:** unlimited
- **cost:** $0
- **signals emitted:** `wikidata_occupation[]`, `wikidata_nationality`, `wikidata_employer`, `wikidata_awards[]`, `wikidata_sitelinks_count`

#### YouTube Data API v3
- **requires:** `youtube_channel_id` OR `youtube_handle`
- **produces:** (none — terminal)
- **method:** `channels.list` (1 quota unit), `search.list` (100 units) — prefer channel lookup over search
- **free tier:** 10,000 units/day
- **cost:** $0
- **signals emitted:** `youtube_subscriber_count`, `youtube_video_count`, `youtube_view_count_total`, `youtube_topics[]`, `youtube_country`, `youtube_published_at`, `youtube_top_videos[]`

#### iTunes Search API
- **requires:** `display_name` OR `podcast_url` OR `podcast_itunes_id`
- **produces:** `podcast_itunes_id`
- **method:** `itunes.apple.com/search?term={name}&entity=podcast` (free, no key)
- **cost:** $0
- **signals emitted:** `podcast_found`, `podcast_episode_count`, `podcast_category`, `podcast_language`, `podcast_rating_count`, `podcast_avg_rating`, `podcast_last_episode_at`

#### Spotify Web API
- **requires:** `spotify_artist_id` OR `podcast_url` OR `display_name`
- **produces:** `spotify_artist_id`
- **method:** Client credentials flow (`api.spotify.com/v1/search`, `artists/{id}`, `shows/{id}`)
- **cost:** $0 (OAuth client credentials, no user login)
- **signals emitted:** `spotify_follower_count`, `spotify_genres[]`, `spotify_popularity`, `spotify_type` (artist | podcast)

#### GitHub API
- **requires:** `github_handle`
- **produces:** (none — terminal)
- **method:** `api.github.com/users/{handle}` (5,000 req/hr with token)
- **cost:** $0
- **signals emitted:** `github_public_repos`, `github_followers`, `github_top_languages[]`, `github_bio`, `github_company`, `github_location`, `github_created_at`

#### BrasilAPI CNPJ
- **requires:** `cnpj` OR `display_name` (fuzzy search via ReceitaWS)
- **produces:** (none — terminal)
- **method:** `brasilapi.com.br/api/cnpj/v1/{cnpj}` or `receitaws.com.br/v1/cnpj/{cnpj}`
- **cost:** $0
- **gate:** Only runs if `subject_jurisdiction == "BR"` or Brazilian phone/address signals present
- **signals emitted:** `cnpj_legal_name`, `cnpj_trade_name`, `cnpj_status`, `cnpj_cnae_primary`, `cnpj_cnae_secondary[]`, `cnpj_open_date`, `cnpj_share_capital`, `cnpj_partners[]`
- **osint_risk:** true (business identity data; may surface partner names)

#### Reddit PRAW
- **requires:** `reddit_username` OR `handle`
- **produces:** (none — terminal)
- **method:** PRAW (official Reddit API, OAuth2 client credentials)
- **cost:** $0
- **signals emitted:** `reddit_karma_total`, `reddit_account_age_days`, `reddit_top_subreddits[]`, `reddit_post_count`, `reddit_comment_count`

#### Twitch API
- **requires:** `twitch_handle` OR `handle`
- **produces:** (none — terminal)
- **method:** `api.twitch.tv/helix/users?login={handle}` (OAuth2 client credentials)
- **cost:** $0
- **signals emitted:** `twitch_follower_count`, `twitch_broadcaster_type`, `twitch_game_category`, `twitch_account_created_at`, `twitch_last_stream_at`

---

### 6.3 Medium Tier

#### Holehe
- **requires:** `email`
- **produces:** `gmail` (if email is Gmail), `registered_services`
- **method:** Self-hosted `holehe` Python package — checks email via 120+ password-recovery endpoints (silent, does not alert target)
- **cost:** $0
- **osint_risk:** true
- **signals emitted:** `holehe_service_count`, `holehe_services[]` (list of service names where account found)
- **note:** `gmail` entity produced only when email domain is `gmail.com`

#### GHunt
- **requires:** `gmail`
- **produces:** `youtube_channel_id` (if Google account has YouTube)
- **method:** Self-hosted `ghunt` CLI — queries Google APIs using session cookies
- **cost:** $0
- **osint_risk:** true
- **signals emitted:** `ghunt_youtube_found`, `ghunt_maps_review_count`, `ghunt_workspace_name`, `ghunt_profile_photo_url`
- **note:** Requires a valid Google session cookie configured via `GHUNT_COOKIES` env variable. If unconfigured, adapter skips gracefully.

#### HaveIBeenPwned (HIBP)
- **requires:** `email`
- **produces:** (none — terminal)
- **method:** `haveibeenpwned.com/api/v3/breachedaccount/{email}` (paid API key required for email search)
- **cost:** ~$0.004/request (HIBP subscription)
- **gate:** Only runs if `HIBP_API_KEY` is set. If unset, adapter emits `status: skipped`.
- **signals emitted:** `hibp_breach_count`, `hibp_breach_names[]`, `hibp_earliest_breach_year`, `hibp_latest_breach_year`, `hibp_sensitive_breach`
- **osint_risk:** true

#### GDELT — Global News Intelligence
- **requires:** `display_name` OR `handle`
- **produces:** (none — terminal)
- **method:** GDELT 2.0 GKG API: `api.gdeltproject.org/api/v2/doc/doc?query={name}&mode=artlist&maxrecords=75`
- **cost:** $0
- **signals emitted:** `gdelt_mention_count`, `gdelt_tone_avg`, `gdelt_tone_positive_pct`, `gdelt_geographic_spread[]`, `gdelt_source_countries[]`, `gdelt_top_articles[]`

#### Google News RSS
- **requires:** `display_name` OR `handle`
- **produces:** (none — terminal)
- **method:** `news.google.com/rss/search?q={name}` (no key required)
- **cost:** $0
- **signals emitted:** `news_article_count_30d`, `news_article_count_1y`, `news_sources[]`, `news_latest_headline`, `news_latest_date`

#### Substack
- **requires:** `substack_url`
- **produces:** (none — terminal)
- **method:** Unofficial Substack API (`{slug}.substack.com/api/v1/posts?limit=10`) + RSS
- **cost:** $0
- **signals emitted:** `substack_post_count`, `substack_has_paid_tier`, `substack_recent_post_count_30d`, `substack_categories[]`

---

### 6.4 Slow Tier

#### Maigret — Cross-Platform Username Enumeration
- **requires:** `handle`
- **produces:** `youtube_handle`, `tiktok_handle`, `twitter_handle`, `instagram_handle`, `github_handle`, `reddit_username`, `twitch_handle`, `linkedin_url`, `substack_url`, `pinterest_handle`, `behance_handle`, `soundcloud_handle`
- **method:** Self-hosted `maigret` Python package — checks handle across 3,000+ sites; runs with `--timeout 300 --retries 1`
- **cost:** $0
- **osint_risk:** true
- **signals emitted:** `maigret_site_count`, `maigret_platform_hits[]`, `maigret_discovered_usernames[]` (alternate handles found on some platforms)
- **max_instances:** 1 (per profile; the handle is fixed)
- **note:** Results feed back into the fast-tier pool. Any new `youtube_handle` discovered unlocks a fresh YouTubeAdapter run if `total_runs < max_adapter_runs` and `max_depth` not exceeded.

---

## 7. Output Format — enrichment_map.json

Written to `projects/{handle}/enrichment_map.json`.

```json
{
  "handle": "filipelauar",
  "enriched_at": "2026-06-02T22:00:00Z",
  "engine_version": "0014.1",
  "status": "complete",
  "dossier_version": "v2",
  "limits": {
    "max_depth": 2,
    "max_adapter_runs": 20,
    "max_cost_usd": 0.50,
    "actual_runs": 9,
    "actual_cost_usd": 0.004,
    "limit_reached": false
  },
  "entity_pool": [
    {
      "type": "youtube_channel_id",
      "value": "UCxyz123",
      "source": "linktree",
      "confidence": 0.95,
      "depth": 1,
      "discovered_at": "2026-06-02T21:50:00Z"
    }
  ],
  "adapter_runs": [
    {
      "adapter_id": "linktree",
      "status": "success",
      "cached": false,
      "ran_at": "2026-06-02T21:48:00Z",
      "duration_s": 2.1,
      "cost_usd": 0.000,
      "entities_produced": 4,
      "signals_produced": 2
    }
  ],
  "signals": [
    {
      "key": "youtube_subscriber_count",
      "value": 4200,
      "unit": "count",
      "confidence": 1.0,
      "method": "api",
      "source": "youtube",
      "osint_risk": false
    },
    {
      "key": "podcast_episode_count",
      "value": 38,
      "unit": "count",
      "confidence": 1.0,
      "method": "api",
      "source": "itunes",
      "osint_risk": false
    },
    {
      "key": "holehe_service_count",
      "value": 23,
      "unit": "count",
      "confidence": 0.9,
      "method": "osint",
      "source": "holehe",
      "osint_risk": true
    }
  ],
  "compliance": {
    "osint_signals_present": true,
    "osint_signal_keys": ["holehe_service_count", "holehe_services"],
    "art9_risk_signals": [],
    "gdpr_basis": "LEGITIMATE_INTERESTS",
    "requires_human_review": true,
    "opt_out_path": "DELETE /profiles/filipelauar"
  }
}
```

### 7.1 enrichment_status.json

Written immediately when fast tier completes; updated on each dossier version build.

```json
{
  "handle": "filipelauar",
  "dossier_version": "v1",
  "started_at": "2026-06-02T21:47:00Z",
  "v1_ready_at": "2026-06-02T21:48:30Z",
  "v2_ready_at": null,
  "v3_ready_at": null,
  "slow_tier_running": true,
  "limit_reached": false
}
```

---

## 8. Pipeline Integration

The Enrichment Engine becomes **Stage 1B**, inserted between Stage 1 (ingest) and the existing
Stage 2 (normalize):

```
Stage 1   INGEST           → 01-raw.json               (unchanged)
Stage 1B  ENRICHMENT       → enrichment_map.json        (NEW)
Stage 2   NORMALIZE        → 02-normalized.json         (reads enrichment_map if present)
Stage 3   FEATURES         → 03-features.json           (LLM sees richer profile)
Stage 6   DOSSIER          → 06-dossier.json + report.md
```

Stage 2 (normalize) reads `enrichment_map.json` if it exists and merges enrichment signals into
the normalized profile. Enrichment is **optional** — if `enrichment_map.json` is absent, Stage 2
runs exactly as before.

Stage 3 LLM prompt receives the full enriched signal set, dramatically widening the feature space
for niche classification, persona inference, and brand fit analysis.

CLI integration:

```bash
# Run enrichment + full pipeline
python3 profile_analyst.py --handle filipelauar --stage all

# Run enrichment only (Stage 1B)
python3 profile_analyst.py --handle filipelauar --stage 1b

# Run enrichment with specific adapters
python3 profile_analyst.py --handle filipelauar --stage 1b --adapters linktree,youtube,itunes

# Skip slow tier (return v1 only)
python3 profile_analyst.py --handle filipelauar --stage 1b --fast-only

# Bust cache for a specific adapter
python3 profile_analyst.py --handle filipelauar --stage 1b --bust-cache maigret
```

---

## 9. Compliance

### 9.1 OSINT Signal Handling

Signals from OSINT adapters (`osint_risk: true`) carry additional handling requirements:

- **Art. 22 gate:** Any profile with `osint_signals_present: true` in `enrichment_map.json`
  automatically sets `art22_applies: true` in Stage 6 compliance flags. Human review is mandatory
  before any campaign selection decision that used OSINT-derived signals. The human review
  override mechanism is a `projects/{handle}/review.log` file — its presence signals that a
  qualified reviewer has approved the profile for automated downstream use. Without this file,
  Stage 6 must emit `art22_applies: true` and must not unblock automated campaign selection.

- **Data minimization:** OSINT signals are stored as structured metrics only — raw adapter
  outputs (full site lists, HTML, screenshots, credential hashes) are never persisted.
  `holehe_services[]` stores service names only; it does not store account URLs or profile
  contents. Adapters enforce this via the `@enforces_structured_output` decorator, which
  validates that `AdapterResult.signals` contains no fields outside the declared `Signal`
  dataclass schema.

- **Confidence floor for dossier surfacing:** OSINT signals with `confidence < 0.7` are stored
  in `enrichment_map.json` but are never surfaced in `report.md` without an explicit
  `--expose-osint-low-confidence` flag. When the flag is set, the report must display a
  `⚠ LOW-CONFIDENCE OSINT SIGNALS EXPOSED` banner before the affected section.

- **Entity-level `art9_risk` inheritance:** At entity construction, the engine sets
  `art9_risk` on produced entities by checking whether `entity.type` is in the producing
  adapter's `art9_risk_entities` set. This is declared per adapter in the adapter class and
  YAML config (new field: `art9_risk_entities: list[str]`). Adapters that do not produce
  Art.9-risk entity types declare an empty list.

- **`gdpr_art9_consent_obtained` gate:** `enrichment_map.json` carries a top-level boolean field
  `gdpr_art9_consent_obtained` (default `false`). The report renderer checks this before including
  any signal with `art9_risk: true`. When `false` or absent, Art.9 signals are silently omitted
  and a `[Art.9 signals redacted — consent not recorded]` note is emitted in their place. This
  converts the Art.9 requirement from a documentation invariant into a runtime-enforced gate.

- **Opt-out cascade:** A `DELETE /profiles/{handle}` request (or `make erase HANDLE={handle}`)
  must securely remove:
  1. `projects/{handle}/enrichment_map.json`
  2. `projects/{handle}/enrichment_status.json`
  3. `projects/{handle}/.enrichment_cache/` (entire directory)
  4. All Stage 1–6 artifacts (delegated to existing erasure pipeline)
  Removal uses `secure_delete(path, passes=3)` — overwrite with random bytes 3× before
  `unlink()` — satisfying GDPR Art.17 "erasure" (data not recoverable from disk).
  The erasure is logged to `compliance/erasure_log.jsonl` with timestamp, handle, and operator.

### 9.2 Multi-Jurisdiction Legal Posture

This pipeline processes data about creators who may be subjects under multiple privacy
frameworks simultaneously. The primary frameworks for this use case:

| Framework | Applies when | Key obligations |
|---|---|---|
| **GDPR** | Data subject is in EU/EEA, or processing occurs in EU | Art.6 legal basis, Art.9 special categories, Art.22 automated decisions, right to erasure |
| **LGPD** (Brazil) | Data subject is in Brazil | Mirrors GDPR structure; applies to `subject_jurisdiction == "BR"`; CNPJ adapter data is subject to LGPD alongside Receita Federal disclosure rules |
| **CCPA** | Data subject is California resident | Right to know, right to delete, right to opt-out of sale; applies when `subject_jurisdiction == "US-CA"` |

`subject_jurisdiction` is propagated from Stage 1 governance metadata. When `UNKNOWN`,
the pipeline defaults to the most restrictive posture (GDPR).

### 9.3 Per-Source Legal Posture

| Adapter | Data category | Legal basis | `art9_risk_entities` |
|---|---|---|---|
| Linktree | PUBLIC_SCRAPE | LEGITIMATE_INTERESTS | [] |
| YouTube | PUBLIC_API | LEGITIMATE_INTERESTS | [] |
| Google KG | PUBLIC_API | LEGITIMATE_INTERESTS | [] |
| Wikidata | OPEN_DATA | LEGITIMATE_INTERESTS | [] |
| iTunes | PUBLIC_API | LEGITIMATE_INTERESTS | [] |
| Spotify | PUBLIC_API | LEGITIMATE_INTERESTS | [] |
| GitHub | PUBLIC_API | LEGITIMATE_INTERESTS | [`github_topics`] — political/advocacy work |
| BrasilAPI | OPEN_DATA | LEGITIMATE_INTERESTS | [`cnpj_partners`] — partner names are personal data |
| GDELT | OPEN_DATA | LEGITIMATE_INTERESTS | [] |
| Google News | PUBLIC_SCRAPE | LEGITIMATE_INTERESTS | [] |
| Substack | PUBLIC_SCRAPE | LEGITIMATE_INTERESTS | [] |
| Reddit | PUBLIC_API | LEGITIMATE_INTERESTS | [`reddit_top_subreddits`] — may reveal political/health/sexuality |
| Twitch | PUBLIC_API | LEGITIMATE_INTERESTS | [] |
| crt.sh | OPEN_DATA | LEGITIMATE_INTERESTS | [] |
| WHOIS | OPEN_DATA | LEGITIMATE_INTERESTS | [] |
| Maigret | OSINT | LEGITIMATE_INTERESTS | [] — presence signals only, not content |
| Holehe | OSINT | LEGITIMATE_INTERESTS | [`holehe_services`] — may reveal health/religion/adult memberships |
| GHunt | OSINT | LEGITIMATE_INTERESTS | [] |
| HIBP | OSINT | LEGITIMATE_INTERESTS | [`hibp_breach_names`] — breach names may signal lifestyle/health |

### 9.4 GDPR / LGPD Art. 9 Signal Flags

The following enrichment signals carry `art9_risk: true`. They must not be surfaced in
`report.md` or used in automated scoring without explicit opt-in consent from the data subject:

| Signal key | Risk category | Reason |
|---|---|---|
| `holehe_services[]` | Health, religion, sexuality | Platform memberships may reveal these categories |
| `reddit_top_subreddits[]` | Political, health, sexuality | Subreddit names directly indicate sensitive interests |
| `github_topics[]` | Political (low risk) | Open-source political/advocacy repos |
| `hibp_breach_names[]` | Health, sexuality (conditional) | Some known breaches are from adult or health platforms |
| `cnpj_partners[]` | Personal data (not Art.9) | Partner identity is personal data requiring minimization |

These signal keys are also listed in `enrichment_map.json` under `compliance.art9_risk_signals[]`
so Stage 6 can gate them without re-inspecting every signal.

---

## 10. Project Layout

```
pipeline/
└── enrichment/
    ├── __init__.py
    ├── engine.py            # EngineConfig, scheduling loop, run_parallel, fixed-point BFS
    ├── entity.py            # Entity, EntityTypeSpec, ENTITY_TYPES, InvalidEntityTypeError
    ├── entity_pool.py       # EntityPool (thread-safe), depth_for_entity()
    ├── adapter.py           # EnrichmentAdapter ABC, AdapterConfig, AdapterResult, Signal
    ├── cache.py             # cache read/write, TTL enforcement, secure_delete()
    ├── registry.py          # loads adapters from config/*.yaml + Python classes; validates at load
    ├── compliance.py        # gdpr_art9_consent_obtained gate, art22 gate, erasure_log
    ├── adapters/
    │   ├── linktree.py
    │   ├── whois.py
    │   ├── crt.py
    │   ├── knowledge_graph.py
    │   ├── wikidata.py
    │   ├── youtube.py
    │   ├── itunes.py
    │   ├── spotify.py
    │   ├── github.py
    │   ├── reddit.py
    │   ├── twitch.py
    │   ├── cnpj.py
    │   ├── holehe.py
    │   ├── ghunt.py
    │   ├── hibp.py
    │   ├── gdelt.py
    │   ├── google_news.py
    │   ├── substack.py
    │   └── maigret.py
    ├── config/              # one YAML per adapter, validated against adapter_config.schema.json
    │   ├── linktree.yaml
    │   ├── youtube.yaml
    │   ├── maigret.yaml
    │   ├── holehe.yaml
    │   ├── hibp.yaml
    │   └── ...
    └── schemas/
        └── adapter_config.schema.json  # JSON Schema draft-2020-12; additionalProperties: false

schemas/
└── enrichment_map.schema.json

projects/{handle}/
├── enrichment_map.json
├── enrichment_status.json  # updated after each tier; includes adapter_errors[], conflicts[]
├── review.log              # presence signals human Art.22 review approval
└── .enrichment_cache/
    └── {sha256_key}.json

compliance/
├── erasure_log.jsonl       # append-only; one line per DELETE /profiles/{handle}
└── ...

logs/
└── {handle}.log            # written when DEBUG=1; adapter start/stop/error events
```

---

## 11. Acceptance Criteria

| ID | Criterion |
|---|---|
| A1 | `python3 profile_analyst.py --handle filipelauar --stage 1b` produces `enrichment_map.json` that validates (zero errors) against `enrichment_map.schema.json` using `jsonschema` draft-7 |
| A2 | Fast tier completes within 60s on a cold cache; `enrichment_status.json` shows `dossier_version: v1` and `v1_ready_at` timestamp |
| A3 | Linktree adapter parses `linktr.ee/vidacomia` and produces ≥1 entity of type `youtube_channel_id` or `podcast_url`; entity value is in canonical normalized form |
| A4 | YouTube adapter, when given a `youtube_channel_id`, emits `youtube_subscriber_count` signal with `confidence=1.0, method="api"` |
| A5 | iTunes adapter, when given `display_name="lifewithai"`, returns a podcast result with `podcast_episode_count > 0` |
| A6 | Maigret adapter, when run against `filipelauar`, produces ≥3 entities of distinct `type` values |
| A7 | Engine stops when `max_adapter_runs=5` is configured; `enrichment_map.json` shows `limit_reached: true` and `actual_runs: 5`; no further adapter calls are made after the limit |
| A8 | Cache hit: re-running Stage 1B within TTL does not increment `actual_runs` for cached adapters; `cached: true` appears in those `adapter_runs[]` entries |
| A9 | `--fast-only` flag runs Tier 0 + Fast Tier only; slow and medium tier adapters are absent from `adapter_runs[]` |
| A10 | A discovered `gmail` entity from Holehe (depth 1) triggers GHunt only if `depth < max_depth=2`; if `max_depth=1`, GHunt does not run and is not present in `adapter_runs[]` |
| A11 | All signals with `osint_risk: true` are absent from `report.md` by default; when `--expose-osint` is passed, all such signals appear with a `⚠ LOW-CONFIDENCE OSINT SIGNALS EXPOSED` banner |
| A12 | `enrichment_map.json` `compliance.art9_risk_signals[]` lists every signal key that carries `art9_risk: true` across all adapter outputs |
| A13 | `make erase HANDLE={handle}` removes `enrichment_map.json`, `enrichment_status.json`, and `.enrichment_cache/` within 2 seconds; erasure is recorded in `compliance/erasure_log.jsonl` |
| A14 | Stage 2 (normalize) runs identically whether `enrichment_map.json` is present or absent — enrichment is additive; no existing Stage 2 field is overwritten by enrichment signals |
| A15 | `make validate` passes: `enrichment_map.schema.json` is valid JSON Schema draft-7; all adapter YAML files pass YAMLLint strict mode and `adapter_id` field matches filename |
| A16 | If an adapter raises an unhandled exception mid-run, the engine logs the error under `enrichment_status.json` → `adapter_errors[]` and continues; remaining adapters still execute; no partial `AdapterResult` is written to the pool |
| A17 | When two adapters produce the same `(entity_type, entity_value)`, only the higher-confidence instance is retained in `entity_pool[]`; the conflict is recorded in `enrichment_status.json` → `conflicts[]` with both sources |
| A18 | All timestamps in `enrichment_map.json` and `enrichment_status.json` are UTC ISO 8601 with `Z` suffix; any non-conforming timestamp fails `make validate` |
| A19 | `python3 profile_analyst.py --list-adapters` prints a table of all registered adapters with `adapter_id`, `tier`, `enabled`, `osint_risk`, and `ttl_hours`; output matches the loaded YAML registry |
| A20 | When supplied with a non-existent handle, the engine exits with code ≠0, prints a human-readable error to stderr, and creates no output files for that handle |
| A21 | Config precedence is enforced: CLI flag overrides env var overrides YAML config; a missing required field (e.g. `HIBP_API_KEY` when `hibp.secrets_required` is non-empty) causes adapter to skip with `status: skipped` in `adapter_runs[]`, not a crash |
| A22 | Each entry in `adapter_runs[]` includes `duration_s`; no entry exceeds the adapter's configured `timeout_s`; a timed-out adapter appears with `status: timeout` and `error: "timeout"` |
| A23 | `Entity.__post_init__` raises `ValueError` for: out-of-range confidence (after clamping log), negative depth, non-ISO-8601 `discovered_at`, and un-normalized value; all four cases are covered by unit tests |
| A24 | `AdapterContractError` is raised at import time (not run time) when a concrete adapter subclass is missing a required class attribute or declares an unknown entity type in `requires` or `produces` |
| A25 | `osint_signals_present: true` in `enrichment_map.json` causes Stage 6 to emit `art22_applies: true` in `06-dossier.json`; without `review.log`, Stage 6 emits `human_review_required: true` |
| A26 | Two successive Stage 1B runs with identical inputs, config, and warm cache produce `entity_pool[]` arrays with the same entities in the same order — determinism is enforced by sorting entities by `(type, value)` before writing |
| A27 | After manually setting a cache entry's `expires_at` to a past timestamp, re-running Stage 1B increments `actual_runs` for that adapter by 1 and writes a fresh cache entry with an updated `cached_at` |
| A28 | Setting `enabled: false` in an adapter's YAML config causes that adapter to be absent from `adapter_runs[]` and contributes no entities or signals, even if its required entity types are present in the pool |
| A29 | `python3 profile_analyst.py --help` exits with code 0 and its output mentions `--handle`, `--stage`, `--fast-only`, `--expose-osint`, and `--max-adapter-runs` |
| A30 | `enrichment_map.json` contains a top-level `"schema_version"` field whose value matches the `"$id"` or `"version"` declared in `enrichment_map.schema.json`; `make validate` fails if they diverge |
