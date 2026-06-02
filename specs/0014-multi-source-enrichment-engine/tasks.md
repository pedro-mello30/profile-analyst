# Tasks 0014 — Multi-Source Enrichment Engine

From `plan.md`. Tracks A–C parallel; D depends on A+B+C; E parallel with D;
F depends on D+E; G depends on F; H parallel with G; I depends on G+H.

---

## Track A — Entity Model

- [x] T1 Write `pipeline/enrichment/__init__.py` (empty package marker)
- [x] T2 Write `pipeline/enrichment/entity.py`: `EntityTypeSpec` frozen dataclass with
      `name`, `pattern`, `normalizer`, `example`, `osint_risk`; `ENTITY_TYPES` dict with all
      24 canonical types and per-type normalizer functions (handle strips `@`, URL lowercases
      host+strips trailing `/`, CNPJ strips punctuation to 14 digits, phone E.164, etc.);
      `InvalidEntityTypeError`; `Entity` frozen dataclass with `__post_init__` validation
      (unknown type → raise, confidence clamp, depth≥0, ISO 8601 timestamp, normalization
      contract); `make_entity()` helper that normalizes then constructs.
- [x] T3 Write `pipeline/enrichment/entity_pool.py`: `EntityPool` class with `threading.Lock`,
      `_store: dict[tuple[str,str], Entity]`, `_provenance: dict[tuple[str,str], list[str]]`.
      Methods: `add()` (True if pool changed, higher confidence wins), `get()`, `by_type()`,
      `by_type_any()`, `provenance()`, `snapshot()` (sorted by type+value, JSON-serializable),
      `all_entities()`, `__len__()`.
- [x] T4 Write `tests/enrichment/__init__.py` and `tests/enrichment/test_entity.py` (29 tests):
      registry has 24 types, osint_risk flags correct, normalizer behaviors per type,
      Entity construction + validation, make_entity() normalizes automatically.
- [x] T5 Write `tests/enrichment/test_entity_pool.py` (14 tests): add/get, higher confidence
      wins, provenance accumulates all sources, snapshot is JSON-serializable, thread-safety
      with 50 concurrent writers.

**Exit (Track A):** 43 tests pass; `make_entity("handle", "@Foo", ...)` produces `value="foo"`.

---

## Track B — Adapter Contract

- [x] T6 Write `pipeline/enrichment/adapter.py`: `AdapterConfig` frozen dataclass; `Signal`
      dataclass with `key, value, unit, confidence, method, source, osint_risk`; `AdapterResult`
      dataclass with `entities, signals, error, cached, ran_at, cost_usd, duration_s`;
      `AdapterContractError`; `EnrichmentAdapter` ABC with `__init_subclass__` that validates
      all required class attrs and raises `AdapterContractError` at module import time
      (not at runtime) for: missing attrs, unknown tier/gdpr_basis/data_category, unknown
      entity types in requires/produces, min_confidence out of [0,1].
- [x] T7 Write `tests/enrichment/test_adapter.py` (9 tests): AdapterConfig constructs, missing
      attr raises AdapterContractError, unknown entity type in requires raises, invalid tier
      raises, valid adapter registers cleanly, Signal and AdapterResult construct correctly.

**Exit (Track B):** 9 tests pass; `AdapterContractError` raised at import time, not runtime.

---

## Track C — Cache Layer

- [x] T8 Write `pipeline/enrichment/cache.py`: `make_cache_key(adapter_id, entity_type,
      entity_value) → str` (SHA-256 hex of `"{adapter_id}:{entity_type}:{entity_value}"`);
      `write_cache()` (atomic `.tmp` → `os.replace`); `read_cache()` (None on miss or expired);
      `is_expired()`; `secure_delete(path, passes=3)` (overwrite with `os.urandom` × passes
      then unlink; handles dirs recursively; noop on missing path).
- [x] T9 Write `tests/enrichment/test_cache.py` (13 tests): determinism, known SHA-256
      constant, miss returns None, TTL=0 expires immediately, secure_delete removes file and
      directory, noop on nonexistent.

**Exit (Track C):** 13 tests pass; `make_cache_key("youtube","youtube_channel_id","UCxyz123")`
matches `hashlib.sha256(b"youtube:youtube_channel_id:UCxyz123").hexdigest()`.

---

## Track D — Engine Core

- [x] T10 Write `pipeline/enrichment/engine.py`:
      `EngineConfig` dataclass (max_depth=2, max_adapter_runs=20, max_cost_usd=0.50,
      min_confidence_global=0.5, slow_tier_timeout_s=600, parallel_workers=8);
      `EngineState` dataclass (config, run_counts, total_runs, total_cost, adapter_errors,
      conflicts);
      `is_runnable()` with `effective_min = max(adapter.min_confidence, global_floor)`;
      `_run_with_cache()` — cache hits increment `run_counts` only, live runs increment
      both `run_counts` and `total_runs/total_cost`;
      `_merge_result()` — records conflicts when two adapters produce same (type,value);
      `run_engine()` implementing Phase 0 (tier=seed, sequential), Phase 1 (fast, parallel,
      blocks), Phase 2 (medium, parallel), Phase 3 (slow, ThreadPoolExecutor with deadline
      via `concurrent.futures.wait(timeout=remaining)` and `executor.shutdown(wait=False)`).
- [x] T11 Write `tests/enrichment/test_engine.py` (15 tests): is_runnable cases (entity
      present, disabled, below adapter floor, global floor overrides adapter floor, depth
      exceeds max, max_adapter_runs hit, max_cost hit, max_instances exhausted), EngineConfig
      defaults, run_engine seeds extraction, fast adapter runs, max_adapter_runs respected.

**Exit (Track D):** 15 tests pass; global confidence floor correctly blocks entities below
`max(adapter.min_confidence, config.min_confidence_global)`.

---

## Track E — Adapter Configs + Schema

- [x] T12 Write `pipeline/enrichment/schemas/adapter_config.schema.json` (JSON Schema draft-7,
      `additionalProperties: false`) with all 16 required fields and their types/enums.
- [x] T13 Write all 19 adapter YAML configs in `pipeline/enrichment/config/`:
      `linktree.yaml`, `whois.yaml`, `crt.yaml`, `knowledge_graph.yaml`, `wikidata.yaml`,
      `youtube.yaml`, `itunes.yaml`, `spotify.yaml`, `github.yaml`, `reddit.yaml`,
      `twitch.yaml`, `cnpj.yaml`, `holehe.yaml`, `ghunt.yaml`, `hibp.yaml`, `gdelt.yaml`,
      `google_news.yaml`, `substack.yaml`, `maigret.yaml`.
      Each: `adapter_id` matches filename, all fields present, validates against schema.
- [x] T14 Write `tests/enrichment/test_registry.py` (6 tests): schema is valid draft-7,
      all 19 adapters configured, all YAML files validate against schema, osint adapters
      flagged, only maigret is slow tier, HIBP requires HIBP_API_KEY.

**Exit (Track E):** 6 tests pass; `make validate` includes adapter config validation.

---

## Track F — Adapter Implementations

- [x] T15 Write `pipeline/enrichment/adapters/__init__.py`
- [x] T16 Write `pipeline/enrichment/adapters/linktree.py` (`LinktreeAdapter`): HTTP GET
      bio_url, regex-extract 8 platform entity types + mailto: email, emit
      `bio_link_platform_count` and `bio_link_platforms[]` signals. depth = seed.depth + 1.
- [x] T17 Write `pipeline/enrichment/adapters/whois.py` (`WhoisAdapter`): RDAP
      `rdap.org/domain/{domain}`, parse registration event for `domain_age_days`.
- [x] T18 Write `pipeline/enrichment/adapters/crt.py` (`CrtAdapter`): crt.sh
      `?q=%.{domain}&output=json`, extract unique subdomains, produce `subdomain` entities.
- [x] T19 Write `pipeline/enrichment/adapters/knowledge_graph.py` (`KnowledgeGraphAdapter`):
      Google KG Search API, produce `wikidata_id`, emit `kg_entity_found/description/types/score`.
- [x] T20 Write `pipeline/enrichment/adapters/wikidata.py` (`WikidataAdapter`): SPARQL
      `query.wikidata.org`, emit `wikidata_occupation/nationality/employer/awards`.
- [x] T21 Write `pipeline/enrichment/adapters/youtube.py` (`YouTubeAdapter`): YouTube Data
      API v3 channels.list, emit `youtube_subscriber_count/video_count/topics[]`.
- [x] T22 Write `pipeline/enrichment/adapters/itunes.py` (`ITunesAdapter`): iTunes Search
      API (free), produce `podcast_itunes_id`, emit `podcast_episode_count/category/rating`.
- [x] T23 Write `pipeline/enrichment/adapters/spotify.py` (`SpotifyAdapter`): client
      credentials OAuth, emit `spotify_follower_count/genres/popularity`.
- [x] T24 Write `pipeline/enrichment/adapters/github.py` (`GitHubAdapter`): GitHub REST
      API, emit `github_public_repos/followers/location/created_at`.
- [x] T25 Write `pipeline/enrichment/adapters/reddit.py` (`RedditAdapter`): PRAW OAuth2,
      emit `reddit_karma_total/account_age_days/top_subreddits[]` (osint_risk=True).
- [x] T26 Write `pipeline/enrichment/adapters/twitch.py` (`TwitchAdapter`): Twitch Helix
      client credentials, emit `twitch_follower_count/broadcaster_type/created_at`.
- [x] T27 Write `pipeline/enrichment/adapters/cnpj.py` (`CNPJAdapter`): BrasilAPI
      `/cnpj/v1/{14digits}`, emit `cnpj_legal_name/trade_name/status/cnae_primary/partners[]`
      (`cnpj_partners` osint_risk=True).
- [x] T28 Write `pipeline/enrichment/adapters/holehe.py` (`HoleheAdapter`): subprocess
      `python3 -m holehe`, emit `holehe_service_count/holehe_services[]` (osint_risk=True),
      produce `gmail` entity if email ends with `@gmail.com`.
- [x] T29 Write `pipeline/enrichment/adapters/ghunt.py` (`GhuntAdapter`): subprocess
      `python3 -m ghunt email`, requires GHUNT_COOKIES secret, produce `youtube_channel_id`.
- [x] T30 Write `pipeline/enrichment/adapters/hibp.py` (`HibpAdapter`): HIBP v3 API,
      requires HIBP_API_KEY, emit `hibp_breach_count/breach_names[]` (osint_risk=True).
      HTTP 404 = no breaches (success, not error).
- [x] T31 Write `pipeline/enrichment/adapters/gdelt.py` (`GdeltAdapter`): GDELT artlist
      API, emit `gdelt_mention_count/tone_avg/positive_pct/source_countries[]`.
- [x] T32 Write `pipeline/enrichment/adapters/google_news.py` (`GoogleNewsAdapter`): Google
      News RSS, parse XML, emit `news_article_count_30d/total/latest_headline/latest_date`.
- [x] T33 Write `pipeline/enrichment/adapters/substack.py` (`SubstackAdapter`): Substack
      `/api/v1/posts`, emit `substack_post_count/has_paid_tier/recent_post_count_30d`.
- [x] T34 Write `pipeline/enrichment/adapters/maigret.py` (`MaigretAdapter`): subprocess
      `python3 -m maigret {handle} --timeout 60 --retries 1 --json`, parse JSON hits,
      produce up to 8 entity types, emit `maigret_site_count/platform_hits/discovered_handles`.

**Exit (Track F):** all 19 adapters import cleanly; `_load_adapters()` returns 19 instances;
all adapters return AdapterResult (never raise); dry_run=True returns empty result.

---

## Track G — Stage 1B Orchestrator

- [x] T35 Write `pipeline/stage1b_enrichment.py`:
      `_ADAPTER_MODULES` dict (19 entries), `_CONFIG_DIR`, `_ART9_SIGNAL_KEYS` frozenset;
      `_load_adapters(adapter_ids)` — loads enabled adapters from YAML + Python classes;
      `list_adapters()` — returns metadata list for `--list-adapters` CLI;
      `run(handle, project_dir, *, fast_only, adapter_ids, bust_cache, engine_config)`:
      reads `02-normalized.json` (raises `FileNotFoundError` if absent), calls
      `assert_within_retention`, calls `run_engine()`, writes `enrichment_map.json`
      (schema_version="enrichment_map/v1", atomic) and `enrichment_status.json`.
- [x] T36 Write `tests/test_stage1b.py` (9 tests): creates enrichment_map, creates status
      file, idempotent, raises FileNotFoundError without Stage 2 artifact, compliance block
      has all required keys, schema_version present, limits block present, seeds in entity_pool,
      list_adapters returns 19.

**Exit (Track G):** 9 tests pass; `run()` raises `FileNotFoundError` when called without
prior Stage 2; `list_adapters()` returns exactly 19 rows.

---

## Track H — JSON Schema + Stage 2 Merge

- [x] T37 Write `schemas/enrichment_map.schema.json` (JSON Schema draft-7):
      required: `handle, enriched_at, engine_version, schema_version (const: "enrichment_map/v1"),
      status, limits, entity_pool, adapter_runs, signals, compliance`;
      `limits` has 6 required sub-fields; `compliance` has 6 required sub-fields.
- [x] T38 Modify `pipeline/stage2_normalize.py`: at end of `run()`, if `enrichment_map.json`
      exists, read it and merge `signals` as `enrichment_signals` key into normalized doc
      (additive only — never overwrites existing fields; all exceptions caught silently).

**Exit (Track H):** `jsonschema.validate(doc, schema)` passes on `enrichment_map.json` output;
Stage 2 runs identically with and without enrichment_map.

---

## Track I — CLI Integration + E2E Tests

- [x] T39 Modify `profile_analyst.py`:
      add `_run_stage1b()` function;
      add `"1b": _run_stage1b` to `STAGE_MAP`;
      update `_parse_stages("all")` to return `["1","2","1b","3","6","7","8","9"]`;
      add argparse flags `--fast-only`, `--adapters`, `--bust-cache`, `--expose-osint`,
      `--list-adapters`; handle `--list-adapters` before dispatch (print table, exit 0);
      pass `fast_only` and `adapters` through to `_run_stage1b()`;
      update `cmd_run()` to route `s == "1b"` with Stage 1B kwargs.
- [x] T40 Write `tests/test_stage1b_e2e.py` (18 tests) covering acceptance criteria:
      A1 (schema validation), A2 (fast-only → v1 dossier with timestamp), A7 (limit_reached),
      A12 (art9_risk_signals), A14 (Stage 2 works without enrichment_map), A17 (conflict
      logging, higher confidence wins), A18 (UTC timestamps), A19 (list_adapters covers all),
      A24 (AdapterContractError at import), A25 (osint_signals_present → requires_human_review),
      A26 (deterministic entity pool), A30 (schema_version matches $id).
- [x] T41 Verify `make test` green (560 tests pass, 11 skipped, 0 failures).
- [x] T42 Verify `python3 profile_analyst.py --list-adapters` prints all 19 adapters.
- [x] T43 Verify `python3 profile_analyst.py --handle filipelauar --stage 1b --fast-only`
      completes and produces schema-valid `enrichment_map.json`.

**Exit (Track I):** 560 tests pass; `make validate` green; `--list-adapters` works.

---

**Total: 43 tasks** across 9 tracks. All tasks completed ✓.

## Out of scope (do not include)

- Live OSINT execution in CI (Maigret, Holehe, GHunt require external tools — integration
  tests use dry_run=True or subprocess mocks)
- Paid-tier HIBP features (HIBP_API_KEY required; absent key → graceful skip)
- Facebook, LinkedIn scrapers (paid/complex ToS; covered by SociaVault if needed later)
- Real-time enrichment / streaming (batch per-profile is sufficient for v1)
- Webhook push for dossier v2/v3 readiness (polling via `enrichment_status.json`)
