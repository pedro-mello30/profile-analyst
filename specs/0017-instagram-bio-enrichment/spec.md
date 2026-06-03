# Spec 0017 — Instagram Bio Enrichment

**Status:** accepted · **Date:** 2026-06-03 · **Depends on:** spec-0014

---

## §1 Problem

The enrichment engine (spec 0014) seeds three entities from `raw_profile`:
`handle`, `display_name`, and `bio_url` (the `website` field).

The `bio` text field is never parsed. For Brazilian creators this is a significant gap:
bios routinely embed emails, phones, CNPJs, and direct URLs that are not exposed via
Linktree or other bio-link aggregators. These entities, if discovered, would unlock
downstream adapters (WHOIS via `domain`, HIBP/GHunt via `email`, CNPJ lookup via `cnpj`)
with zero additional API cost.

Additionally, the enrichment adapter contract (`AdapterConfig`) has no mechanism for
adapters to access raw source data. Every adapter receives only a list of `Entity` objects.
This is correct for network adapters, but creates an artificial barrier for local-parsing
adapters that could produce high-value entities from already-ingested data at zero cost.

---

## §2 Solution Overview

Three changes, each independently testable:

1. **`AdapterContext`** — a new dataclass added to `AdapterConfig` that carries
   `raw_profile`, `raw_media`, and `source_platform`. Opt-in: adapters that don't need
   it ignore `config.context`. All existing adapters are unaffected.

2. **`BioEntityExtractor`** — a reusable text-parsing class in
   `pipeline/enrichment/extractors/bio.py`. Input: bio text + optional website URL.
   Output: `list[(entity_type, normalized_value, confidence)]`. No adapter dependency.

3. **`InstagramBioAdapter`** — a `tier=seed, priority=0` adapter that reads
   `config.context.raw_profile["bio"]` and delegates to `BioEntityExtractor`.
   Runs before Linktree (priority=1) so extracted domains seed WHOIS in the same
   engine run.

---

## §3 AdapterContext Contract

### §3.1 Dataclass definition

```python
@dataclass
class AdapterContext:
    raw_profile: dict | None = None
    raw_media: list[dict] | None = None
    source_platform: str | None = None
```

Location: `pipeline/enrichment/adapter.py`, inserted before `AdapterConfig`.

### §3.2 AdapterConfig update

`AdapterConfig` gains one optional field at the end:

```python
context: AdapterContext | None = None
```

`AdapterConfig` is `frozen=True`. Adding a field with a default does not break existing
instantiation sites that use positional or keyword arguments without `context`.

### §3.3 Engine wiring

`run_engine()` in `pipeline/enrichment/engine.py` gains an optional parameter:

```python
def run_engine(
    seed_data: dict,
    adapters: list[EnrichmentAdapter],
    config: EngineConfig,
    cache_dir: Path,
    run_id: str | None = None,
    raw_media: list[dict] | None = None,    # NEW
) -> tuple[EntityPool, EngineState, list[AdapterResult]]:
```

The `AdapterConfig` constructed inside `run_engine` includes:

```python
context=AdapterContext(
    raw_profile=seed_data,
    raw_media=raw_media,
    source_platform="instagram",
)
```

`stage1b_enrichment.py` passes `raw_media=raw.get("raw_media", [])` when calling
`run_engine`.

---

## §4 BioEntityExtractor

### §4.1 Location

`pipeline/enrichment/extractors/__init__.py` (empty)
`pipeline/enrichment/extractors/bio.py`

### §4.2 Interface

```python
class BioEntityExtractor:
    def extract(
        self,
        bio: str | None,
        *,
        website: str | None = None,
    ) -> list[tuple[str, str, float]]:
        ...
```

Returns a list of `(entity_type, raw_value, confidence)` tuples. Does not call
`make_entity` — that is the adapter's responsibility so validation errors are caught
per-entity without aborting the whole extraction.

### §4.3 Extraction rules

| Entity type  | Source        | Regex / method                                  | Confidence |
|---|---|---|---|
| `email`      | bio text      | Standard RFC-5321-safe pattern                  | 0.7        |
| `cnpj`       | bio text      | Formatted `##.###.###/####-##` → 14 digits      | 0.85       |
| `cnpj`       | bio text      | Raw 14 consecutive digits (lower priority)      | 0.6        |
| `phone`      | bio text      | `+55`-anchored, E.164 normalised, 10–15 digits  | 0.6        |
| `website_url`| bio text + website field | URL regex `https?://...`             | 0.9        |
| `domain`     | bio text + website field | netloc from URL, strip `www.`        | 0.9        |

**Domain exclusion list** (`_SKIP_DOMAINS`): `linktr.ee`, `linktree.com`, `bio.link`,
`beacons.ai`, `msha.ke`, `campsite.bio`, `carrd.co`. These are bio-link aggregators
already seeded as `bio_url`; emitting them as `domain` would trigger WHOIS on a CDN.

**`None` / empty bio** → returns `[]` without raising.

### §4.4 Deduplication

The extractor returns all matches including duplicates. The adapter deduplicates by
`(type, value)` before constructing `Entity` objects.

---

## §5 InstagramBioAdapter

### §5.1 Class attributes

| Attribute        | Value                                    |
|---|---|
| `adapter_id`     | `"instagram_bio"`                        |
| `display_name`   | `"Instagram Bio Entity Extractor"`       |
| `requires`       | `["handle"]`                             |
| `produces`       | `["email", "phone", "cnpj", "website_url", "domain"]` |
| `tier`           | `"seed"`                                 |
| `priority`       | `0` (before Linktree at priority=1)      |
| `cost_usd`       | `0.0`                                    |
| `timeout_s`      | `5`                                      |
| `retry_max`      | `0`                                      |
| `rate_limit_rpm` | `0`                                      |
| `ttl_hours`      | `168` (bio changes rarely)               |
| `min_confidence` | `0.5`                                    |
| `max_instances`  | `1`                                      |
| `osint_risk`     | `True` (email/phone/cnpj are PII)        |
| `secrets_required` | `[]`                                   |
| `gdpr_basis`     | `"LEGITIMATE_INTERESTS"`                 |
| `data_category`  | `"PUBLIC_SCRAPE"`                        |
| `tos_compliant`  | `True`                                   |

### §5.2 run() contract

```
Input:
  seed_entities: list[Entity]  — contains at least handle entity
  config: AdapterConfig        — config.context.raw_profile["bio"] is the input text

Guard clauses (return empty AdapterResult, no error):
  - config.dry_run is True
  - config.context is None
  - config.context.raw_profile is None

Processing:
  1. bio = config.context.raw_profile.get("bio") or ""
  2. website = config.context.raw_profile.get("website")
  3. depth = seed_entities[0].depth + 1 (or 1 if no seeds)
  4. hits = BioEntityExtractor().extract(bio, website=website)
  5. For each (entity_type, raw_value, confidence) in hits:
       try: make_entity(entity_type, raw_value, source=adapter_id, confidence, depth, now)
       except: skip (validation error — value didn't match type's pattern)
  6. Deduplicate by (type, value)
  7. Emit Signal("bio_entity_count", len(deduped), "count", 1.0, "computed", adapter_id, False)

Output:
  AdapterResult(entities=deduped, signals=[bio_entity_count], error=None, cost_usd=0.0)
```

### §5.3 Location

`pipeline/enrichment/adapters/instagram_bio.py`

### §5.4 YAML config

`pipeline/enrichment/config/instagram_bio.yaml` — mirrors class attributes; `enabled: true`.

### §5.5 Registration

`stage1b_enrichment.py._ADAPTER_MODULES` gains:

```python
"instagram_bio": "pipeline.enrichment.adapters.instagram_bio.InstagramBioAdapter",
```

as the **first entry** (dictionary iteration order = load order; priority=0 guarantees
scheduling order is enforced by the engine regardless of dict order, but first-in-dict
makes intent explicit).

---

## §6 Out of scope (YAGNI)

| Deferred | Reason |
|---|---|
| `CaptionMentionsAdapter` (reads `raw_media`) | `AdapterContext.raw_media` is wired now; the adapter itself is a separate spec |
| `source_platform` auto-detection | Hardcoded `"instagram"` for now; generalise when a second platform is ingested |
| Phone validation beyond E.164 length check | Carrier lookup is out of scope; confidence=0.6 reflects fuzzy extraction |
| CNPJ checksum validation | Digits are correct; CNPJ lookup adapter handles validity |
| Extractor for TikTok/YouTube bio | Same `BioEntityExtractor` class; trigger via a future `TikTokBioAdapter` |

---

## §7 Compliance

`osint_risk: True` on the adapter because extracted emails, phones, and CNPJs are PII.

All three entity types (`email`, `phone`, `cnpj`) already carry `osint_risk: True` in the
entity registry (`entity.py`). The enrichment engine's existing OSINT gating
(`_ART9_SIGNAL_KEYS`, `compliance.requires_human_review`) applies automatically.

No new GDPR surface is introduced — the bio text is already ingested and stored in
`01-raw.json` under `LEGITIMATE_INTERESTS`.

---

## §8 Test surface

| File | Tests | Coverage |
|---|---|---|
| `tests/enrichment/test_adapter_context.py` | 3 | AdapterContext fields, AdapterConfig opt-in |
| `tests/enrichment/test_engine.py` (appended) | 1 | context passes through to adapters |
| `tests/enrichment/test_bio_extractor.py` | 11 | all entity types, edge cases, empty/None |
| `tests/enrichment/adapters/test_instagram_bio.py` | 9 | adapter contract, guard clauses, signals |
| `tests/test_stage1b.py` (updated) | 1 updated | count 19→20, instagram_bio in registry |

Total new/updated tests: ~25
