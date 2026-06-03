# Plan 0017 — Instagram Bio Enrichment

Derived from `spec.md`. Four independent tracks (A–D) plus integration track E.
Tracks A–D can be parallelised; E depends on all four.

---

## Architecture

```
pipeline/enrichment/adapter.py
  + AdapterContext(raw_profile, raw_media, source_platform)
  + AdapterConfig.context: AdapterContext | None = None

pipeline/enrichment/engine.py
  + run_engine(..., raw_media=None)
  + passes AdapterContext to every adapter via AdapterConfig

pipeline/stage1b_enrichment.py
  + passes raw_media=raw.get("raw_media", []) to run_engine

pipeline/enrichment/extractors/
  __init__.py                         (new package)
  bio.py  →  BioEntityExtractor       (text → [(type, value, confidence)])

pipeline/enrichment/adapters/
  instagram_bio.py  →  InstagramBioAdapter
                       tier=seed, priority=0
                       reads config.context.raw_profile["bio"]
                       delegates to BioEntityExtractor

pipeline/enrichment/config/
  instagram_bio.yaml                  (adapter YAML config)

pipeline/stage1b_enrichment.py
  _ADAPTER_MODULES["instagram_bio"] = "...InstagramBioAdapter"  (first entry)
```

---

## Track A — AdapterContext contract

**Touches:** `pipeline/enrichment/adapter.py`
**Tests:** `tests/enrichment/test_adapter_context.py` (3 tests, new file)

- T1 Add `AdapterContext` dataclass (raw_profile, raw_media, source_platform — all optional)
- T2 Add `context: AdapterContext | None = None` as last field in `AdapterConfig`
- T3 Write 3 tests: accepts context, context is optional, defaults are None
- T4 Verify full suite passes (no existing callers break)

**Exit:** AdapterConfig instantiates with and without context; existing tests green.

---

## Track B — Engine wiring

**Touches:** `pipeline/enrichment/engine.py`, `pipeline/stage1b_enrichment.py`
**Tests:** `tests/enrichment/test_engine.py` (1 test appended)
**Depends on:** Track A

- T5 Add `raw_media: list[dict] | None = None` param to `run_engine()`
- T6 Build `AdapterContext(raw_profile=seed_data, raw_media=raw_media, source_platform="instagram")` in engine
- T7 Pass `context=AdapterContext(...)` when constructing `AdapterConfig` in engine
- T8 Update `stage1b_enrichment.py` call: add `raw_media=raw.get("raw_media", [])`
- T9 Write 1 engine test: `test_engine_passes_context_to_adapters` using a ContextCapture adapter
- T10 Verify full suite passes

**Exit:** Adapters receive `config.context.raw_profile == seed_data` and `config.context.raw_media`.

---

## Track C — BioEntityExtractor

**Touches:** `pipeline/enrichment/extractors/` (new package)
**Tests:** `tests/enrichment/test_bio_extractor.py` (11 tests, new file)
**Independent of:** Tracks A, B (no dependency)

- T11 Create `pipeline/enrichment/extractors/__init__.py` (empty)
- T12 Implement `BioEntityExtractor.extract(bio, *, website=None)` in `extractors/bio.py`
      — compiled regexes for email, CNPJ formatted, CNPJ raw, phone (E.164), URL
      — domain from URL netloc, skip _SKIP_DOMAINS
      — returns list of (entity_type, raw_value, confidence) tuples
      — None/empty bio → []
- T13 Write 11 tests covering all entity types, edge cases, aggregator exclusion, empty/None
- T14 Verify full suite passes

**Exit:** 11 extractor tests green; `BioEntityExtractor().extract(None) == []`.

---

## Track D — InstagramBioAdapter

**Touches:** `pipeline/enrichment/adapters/instagram_bio.py`, `pipeline/enrichment/config/instagram_bio.yaml`
**Tests:** `tests/enrichment/adapters/test_instagram_bio.py` (9 tests, new file)
**Depends on:** Track C (uses BioEntityExtractor), Track A (uses AdapterContext type)

- T15 Implement `InstagramBioAdapter` with full class-attribute contract
      — tier=seed, priority=0, cost_usd=0.0, osint_risk=True
      — guard clauses: dry_run, no context, no raw_profile → empty AdapterResult
      — delegates to `BioEntityExtractor().extract(bio, website=website)`
      — deduplicates by (type, value)
      — emits Signal("bio_entity_count", len(deduped), ...)
- T16 Create `instagram_bio.yaml` config
- T17 Write 9 tests: email extraction, domain extraction, CNPJ, no-context guard, dry_run guard,
      empty bio, bio_entity_count signal, cost_usd==0.0, source on entities
- T18 Verify full suite passes

**Exit:** 9 adapter tests green; contract validated at import time via `__init_subclass__`.

---

## Track E — Registration and integration

**Touches:** `pipeline/stage1b_enrichment.py`, `tests/test_stage1b.py`
**Tests:** `tests/test_stage1b.py` (1 test updated)
**Depends on:** Tracks A + B + C + D

- T19 Add `"instagram_bio": "...InstagramBioAdapter"` as first entry in `_ADAPTER_MODULES`
- T20 Update `test_list_adapters_returns_19` → `test_list_adapters_returns_20`, assert `instagram_bio` in ids
- T21 Run `python3 profile_analyst.py --handle sample_creator --stage 1b`
      Verify `adapter_runs` contains `instagram_bio`; verify bio entities present in `entity_pool`
- T22 Full suite: `make test` — all 573+ tests pass, 0 new failures
- T23 `make validate` — green

**Exit:** `list_adapters()` returns 20 adapters; `instagram_bio` fires on `sample_creator`.
