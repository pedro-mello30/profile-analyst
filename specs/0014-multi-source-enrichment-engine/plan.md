# Plan 0014 — Multi-Source Enrichment Engine

Derived from `spec.md`. Implementation is complete and integrated. This document records the
architecture choices and track structure that guided the build.

---

## Architecture

```
profile_analyst.py  (CLI)
  --stage 1b  --fast-only  --adapters  --bust-cache  --list-adapters
         │
         ▼
pipeline/stage1b_enrichment.py               (Stage 1B orchestrator)
  run(handle, project_dir, fast_only, adapter_ids, bust_cache, engine_config)
  │   reads: 02-normalized.json              (Stage 2 must run first)
  │   writes: enrichment_map.json
  │           enrichment_status.json
         │
         ▼
pipeline/enrichment/engine.py               (Fixed-point BFS scheduler)
  EngineConfig(max_depth=2, max_adapter_runs=20, max_cost_usd=0.50, ...)
  EngineState (run_counts, total_runs, total_cost, adapter_errors, conflicts)
  is_runnable(adapter, pool, state)         ← effective_min = max(adapter.min_confidence,
  run_engine(seed_data, adapters, config)      state.config.min_confidence_global)
         │
    ┌────┴────────────────────────────────────────────────────────────────┐
    │                   Tier Execution                                     │
    │                                                                      │
    │  Phase 0  Tier 0  (sequential, ~5s)                                 │
    │    LinktreeAdapter → WhoisAdapter → CrtAdapter                       │
    │                                                                      │
    │  Phase 1  Fast tier  (parallel, blocks dossier v1, ~30s)            │
    │    KnowledgeGraphAdapter  WikidataAdapter  YouTubeAdapter            │
    │    ITunesAdapter  SpotifyAdapter  GitHubAdapter  RedditAdapter       │
    │    TwitchAdapter  CNPJAdapter                                        │
    │                                                                      │
    │  Phase 2  Medium tier  (parallel, async → dossier v2)               │
    │    HoleheAdapter  GhuntAdapter  HibpAdapter                          │
    │    GdeltAdapter  GoogleNewsAdapter  SubstackAdapter                  │
    │                                                                      │
    │  Phase 3  Slow tier  (wall-clock bounded → dossier v3)              │
    │    MaigretAdapter                                                    │
    │    └─ produces new entities → unlocks fast/medium adapters           │
    └─────────────────────────────────────────────────────────────────────┘
         │
         ▼
pipeline/enrichment/entity_pool.py          (thread-safe EntityPool)
  EntityPool keyed by (type, value); higher confidence wins on duplicate
  provenance dict tracks all contributing sources
         │
         ▼
pipeline/enrichment/cache.py                (per-adapter cache)
  make_cache_key(adapter_id, entity_type, entity_value) → sha256 hex
  write_cache / read_cache (TTL per adapter, atomic .tmp → os.replace)
  secure_delete(path, passes=3)             ← GDPR Art.17 erasure
         │
         ▼
schemas/enrichment_map.schema.json          (JSON Schema draft-7)
pipeline/enrichment/schemas/adapter_config.schema.json
```

### Key data structures

```
Entity (frozen dataclass):
  type: str                ← from ENTITY_TYPES registry (24 canonical types)
  value: str               ← normalized (ENTITY_TYPES[type].normalizer applied)
  source: str              ← adapter_id that produced this
  confidence: float        ← 0.0–1.0; clamped in __post_init__
  depth: int               ← hops from seed (0 = seed)
  discovered_at: str       ← UTC ISO 8601

EntityTypeSpec (frozen dataclass):
  name: str
  pattern: re.Pattern      ← value must match after normalization
  normalizer: Callable     ← call before constructing Entity
  example: str
  osint_risk: bool         ← True for email, gmail, cnpj, phone

EnrichmentAdapter (ABC):
  adapter_id, display_name, requires, produces
  tier, priority, cost_usd, timeout_s, retry_max, rate_limit_rpm
  ttl_hours, min_confidence, max_instances, osint_risk
  secrets_required, gdpr_basis, data_category, tos_compliant
  __init_subclass__() validates all attrs at import time
  run(seed_entities, config) → AdapterResult

AdapterConfig (frozen dataclass):
  profile_id, run_id, max_depth, max_cost_usd, max_runtime_s
  secrets, osint_enabled, cache_enabled, dry_run
```

---

## Implementation tracks (dependency-ordered)

### Track A — Entity Model (foundation)

Write `pipeline/enrichment/__init__.py`, `entity.py`, `entity_pool.py`.

`EntityTypeSpec` + `ENTITY_TYPES` registry with all 24 canonical types and per-type normalizers.
`Entity` frozen dataclass with `__post_init__` validation. `make_entity()` helper.
`EntityPool` thread-safe container.

**Exit:** all 43 tests in `tests/enrichment/test_entity.py` + `test_entity_pool.py` pass.

---

### Track B — Adapter Contract (parallel with A)

Write `pipeline/enrichment/adapter.py`.

`AdapterConfig` frozen dataclass, `Signal` dataclass, `AdapterResult` dataclass,
`EnrichmentAdapter` ABC with `__init_subclass__` validation at import time.

**Exit:** all 9 tests in `tests/enrichment/test_adapter.py` pass; a mis-configured adapter
raises `AdapterContractError` when its module is imported.

---

### Track C — Cache Layer (parallel with A, B)

Write `pipeline/enrichment/cache.py`.

`make_cache_key()` (SHA-256, unit-tested against known constant), `write_cache()`, `read_cache()`,
`is_expired()`, `secure_delete(passes=3)`.

**Exit:** all 13 tests in `tests/enrichment/test_cache.py` pass.

---

### Track D — Engine Core (depends on A, B, C)

Write `pipeline/enrichment/engine.py`.

`EngineConfig`, `EngineState`, `is_runnable()` with global confidence floor, `_run_with_cache()`
with distinct run_counts vs total_runs semantics on cache hits, `run_engine()` implementing
Phase 0–3 with `ThreadPoolExecutor` and wall-clock deadline for slow tier.

**Exit:** all 15 tests in `tests/enrichment/test_engine.py` pass.

---

### Track E — Adapter Configs + Schema (parallel with D)

Write `pipeline/enrichment/config/*.yaml` (19 files) and
`pipeline/enrichment/schemas/adapter_config.schema.json`.

Each YAML: `adapter_id` matches filename, all required fields present, validated against schema.

**Exit:** all 6 tests in `tests/enrichment/test_registry.py` pass; `make validate` green.

---

### Track F — Adapter Implementations (depends on D, E)

Write `pipeline/enrichment/adapters/*.py` — all 19 adapters.

**Tier 0:** `linktree.py`, `whois.py`, `crt.py`
**Fast:** `knowledge_graph.py`, `wikidata.py`, `youtube.py`, `itunes.py`, `spotify.py`,
          `github.py`, `reddit.py`, `twitch.py`, `cnpj.py`
**Medium:** `holehe.py`, `ghunt.py`, `hibp.py`, `gdelt.py`, `google_news.py`, `substack.py`
**Slow:** `maigret.py`

Each adapter: dry_run guard, graceful error return (never raises), class attrs match YAML.

**Exit:** all 19 adapters import cleanly; `_load_adapters()` returns 19 instances;
dry_run=True returns empty AdapterResult without network calls.

---

### Track G — Stage 1B Orchestrator (depends on D, E, F)

Write `pipeline/stage1b_enrichment.py`.

`run()`, `_load_adapters()`, `list_adapters()`. Reads `02-normalized.json` for seeds,
calls `run_engine()`, writes `enrichment_map.json` + `enrichment_status.json` atomically.

**Exit:** all 9 tests in `tests/test_stage1b.py` pass.

---

### Track H — JSON Schema + Stage 2 Merge (parallel with G)

Write `schemas/enrichment_map.schema.json` (draft-7, `schema_version` const).
Modify `pipeline/stage2_normalize.py` to optionally merge enrichment signals (additive only).

**Exit:** `jsonschema.validate(doc, schema)` passes on `enrichment_map.json` output;
Stage 2 runs identically with and without enrichment_map present.

---

### Track I — CLI Integration + E2E Tests (depends on G, H)

Modify `profile_analyst.py`: add `_run_stage1b()`, `"1b"` to STAGE_MAP,
update `all` stages order to `["1","2","1b","3","6","7","8","9"]`,
add `--fast-only`, `--adapters`, `--bust-cache`, `--expose-osint`, `--list-adapters` flags.

Write `tests/test_stage1b_e2e.py` covering acceptance criteria A1–A30.

**Exit:** `python3 profile_analyst.py --list-adapters` prints all 19; 560 total tests pass.

---

**Dependency graph:**

```
A (Entity)  ─┐
B (Adapter) ─┼─→ D (Engine) ─→ F (Adapters) ─→ G (Orchestrator) ─→ I (CLI + E2E)
C (Cache)   ─┘                                        │
             E (Configs) ──────────────────────────────┘
             H (Schema + Stage2 merge) ──────────────────────────────┘
```

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| External API rate limits (Gemini 429, HIBP credits) | Ensemble ran on free-tier fallback models; `hibp` skip-gated on `HIBP_API_KEY` absent |
| Maigret timeout on slow machines | `slow_tier_timeout_s=600` default; `--fast-only` skips slow tier entirely |
| Thread-safety in EntityPool under heavy parallel load | `threading.Lock` on all reads and writes; tested with 50 concurrent writers |
| Cache key collisions | SHA-256 (2^256 collision resistance); unit-tested against known constant |
| OSINT signal surfacing without consent | `gdpr_art9_consent_obtained=False` default; OSINT signals gated from `report.md` unless `--expose-osint` |
| Stage 2 fails if enrichment engine errors | Enrichment is additive — Stage 2 catches all enrichment exceptions and proceeds |
