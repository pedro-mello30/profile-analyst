# Tasks 0017 — Instagram Bio Enrichment

From `plan.md`. Tracks A–D are independent and can be parallelised.
Track E depends on A + B + C + D.

> **Rule:** This file is a transport artifact. After deploy to Linear, execution state lives
> in Linear only. Do not add `status:` fields here.

---

## Track A — AdapterContext contract

**[Spec-0017] T1–T4: Add AdapterContext to adapter contract**

**Group:** Track A — AdapterContext contract (independent)

Add `AdapterContext` dataclass and wire it into `AdapterConfig` as an optional field.

**Files:**
- Modify: `pipeline/enrichment/adapter.py`
- Create: `tests/enrichment/test_adapter_context.py`

**Implementation notes:**
- `AdapterContext` is a plain `@dataclass` (not frozen) with three all-optional fields:
  `raw_profile: dict | None = None`, `raw_media: list[dict] | None = None`,
  `source_platform: str | None = None`
- `AdapterConfig` gains `context: AdapterContext | None = None` as its last field
- `AdapterConfig` is `frozen=True` — adding a field with default is backward-compatible
- Do NOT add `context` to `_REQUIRED_ATTRS` in the contract checker

**Acceptance Criteria:**
- [ ] `AdapterContext` importable from `pipeline.enrichment.adapter`
- [ ] `AdapterConfig` instantiates without `context` arg (existing callers unbroken)
- [ ] `AdapterConfig` accepts `context=AdapterContext(raw_profile={...})`
- [ ] `AdapterContext()` with no args has `raw_profile=None`, `raw_media=None`, `source_platform=None`
- [ ] Test `test_adapter_config_accepts_context` passes
- [ ] Test `test_adapter_config_context_is_optional` passes
- [ ] Test `test_adapter_context_raw_media_defaults_to_none` passes
- [ ] Full suite: no regressions

---

## Track B — Engine wiring

**[Spec-0017] T5–T10: Wire AdapterContext through run_engine and stage1b**

**Group:** Track B — Engine wiring (depends on Track A)

Add `raw_media` parameter to `run_engine()` and pass `AdapterContext` to every adapter.

**Files:**
- Modify: `pipeline/enrichment/engine.py`
- Modify: `pipeline/stage1b_enrichment.py`
- Modify: `tests/enrichment/test_engine.py` (append test)

**Implementation notes:**
- `run_engine` signature: add `raw_media: list[dict] | None = None` as last param
- Inside `run_engine`, build `AdapterContext(raw_profile=seed_data, raw_media=raw_media, source_platform="instagram")` before `AdapterConfig` construction
- `stage1b_enrichment.py` call to `run_engine` adds `raw_media=raw.get("raw_media", [])`
- Add `AdapterContext` import to `engine.py` top-level imports

**Acceptance Criteria:**
- [ ] `run_engine(seed_data, adapters, config, cache_dir)` still works (no breaking change)
- [ ] `run_engine(..., raw_media=[...])` passes media to adapters via `config.context.raw_media`
- [ ] `config.context.raw_profile == seed_data` inside every adapter run
- [ ] `config.context.source_platform == "instagram"` inside every adapter run
- [ ] Test `test_engine_passes_context_to_adapters` passes
- [ ] Stage 1B run passes `raw_media` from `01-raw.json` to the engine
- [ ] Full suite: no regressions

---

## Track C — BioEntityExtractor

**[Spec-0017] T11–T14: Implement BioEntityExtractor**

**Group:** Track C — BioEntityExtractor (independent)

Create a reusable text-extraction class for identity entities in bio text.

**Files:**
- Create: `pipeline/enrichment/extractors/__init__.py`
- Create: `pipeline/enrichment/extractors/bio.py`
- Create: `tests/enrichment/test_bio_extractor.py`

**Implementation notes:**
- Interface: `BioEntityExtractor().extract(bio: str | None, *, website: str | None = None) -> list[tuple[str, str, float]]`
- Use compiled `re` patterns (define at module level, not inside `extract()`)
- Skip domains: `linktr.ee`, `linktree.com`, `bio.link`, `beacons.ai`, `msha.ke`, `campsite.bio`, `carrd.co`
- CNPJ formatted (`##.###.###/####-##`) confidence=0.85; raw 14-digit confidence=0.6
- Returns `[]` for `None` or empty bio — never raises
- Does NOT call `make_entity` — caller handles validation

**Acceptance Criteria:**
- [ ] `BioEntityExtractor().extract("contato@x.com")` returns `[("email", "contato@x.com", 0.7)]`
- [ ] Formatted CNPJ `12.345.678/0001-90` → `("cnpj", "12345678000190", 0.85)`
- [ ] Raw 14-digit CNPJ `12345678000190` → `("cnpj", "12345678000190", 0.6)`
- [ ] `website="https://linktr.ee/x"` → no `domain` entity produced for `linktr.ee`
- [ ] `website="https://vidacomia.com.br"` → `("domain", "vidacomia.com.br", 0.9)` produced
- [ ] `BioEntityExtractor().extract(None) == []`
- [ ] `BioEntityExtractor().extract("") == []`
- [ ] Returns `list[tuple[str, str, float]]` — 3-tuples always
- [ ] All 11 tests in `test_bio_extractor.py` pass
- [ ] Full suite: no regressions

---

## Track D — InstagramBioAdapter

**[Spec-0017] T15–T18: Implement InstagramBioAdapter**

**Group:** Track D — InstagramBioAdapter (depends on Tracks A + C)

Implement the adapter that reads bio text from `config.context` and delegates to `BioEntityExtractor`.

**Files:**
- Create: `pipeline/enrichment/adapters/instagram_bio.py`
- Create: `pipeline/enrichment/config/instagram_bio.yaml`
- Create: `tests/enrichment/adapters/test_instagram_bio.py`

**Implementation notes:**
- `tier="seed"`, `priority=0` — runs before Linktree (priority=1)
- Guard clauses at top of `run()`: return empty `AdapterResult` if `dry_run`, `context is None`, or `context.raw_profile is None`
- `depth = seed_entities[0].depth + 1 if seed_entities else 1`
- After `make_entity` calls, deduplicate by `(type, value)` — keep first occurrence
- Emit exactly one signal: `Signal(key="bio_entity_count", value=len(deduped), unit="count", confidence=1.0, method="computed", source=adapter_id, osint_risk=False)`
- `osint_risk=True` on the adapter class (PII outputs)
- YAML config must mirror all class attributes

**Acceptance Criteria:**
- [ ] Adapter contract validated at import time via `__init_subclass__` (no `AdapterContractError` on import)
- [ ] `run()` extracts email from `config.context.raw_profile["bio"]`
- [ ] `run()` extracts domain from `config.context.raw_profile["website"]`
- [ ] `run()` extracts CNPJ from bio text
- [ ] `run()` returns empty result when `config.context is None` (no error)
- [ ] `run()` returns empty result when `config.dry_run is True`
- [ ] `run()` returns empty result when `bio is None or ""`
- [ ] `result.cost_usd == 0.0` always
- [ ] All entities have `source == "instagram_bio"`
- [ ] `bio_entity_count` signal present in `result.signals`
- [ ] All 9 tests in `test_instagram_bio.py` pass
- [ ] Full suite: no regressions

---

## Track E — Registration and integration

**[Spec-0017] T19–T23: Register adapter, smoke test, final gate**

**Group:** Track E — Registration (depends on Tracks A + B + C + D)

Register the new adapter in the orchestrator, update the count test, run smoke test.

**Files:**
- Modify: `pipeline/stage1b_enrichment.py` (`_ADAPTER_MODULES`)
- Modify: `tests/test_stage1b.py` (rename count test, update assertion)

**Implementation notes:**
- Add `"instagram_bio": "pipeline.enrichment.adapters.instagram_bio.InstagramBioAdapter"` as the **first** key in `_ADAPTER_MODULES`
- Rename `test_list_adapters_returns_19` → `test_list_adapters_returns_20`; update assertion to `len(rows) == 20` and add `assert "instagram_bio" in ids`

**Acceptance Criteria:**
- [ ] `list_adapters()` returns 20 rows
- [ ] `"instagram_bio"` in `{r["adapter_id"] for r in list_adapters()}`
- [ ] `python3 profile_analyst.py --handle sample_creator --stage 1b` completes without error
- [ ] `enrichment_map.json` contains adapter run entry with `adapter_id == "instagram_bio"`
- [ ] Bio entities (email, domain, etc.) appear in `entity_pool` for `sample_creator`
- [ ] `make test` — 573+ tests pass, 0 new failures
- [ ] `make validate` — green
