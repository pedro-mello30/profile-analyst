# Plan 0001 — Social-Media Associations Profile: Instagram-Seeded Unified Creator Dossier

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
v1 ships Tracks A–F (Stages 1–3 + 6 + compliance + tests); Tracks G–H are v2/v3 scaffolding.

## Architecture (reference)

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                   profile_analyst.py  (CLI)                      │
  │  --handle <ig>  --stage all|1,2,3,6   erase  gc                 │
  └──────────┬───────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │                  SourceAdapter ABC  (adapters/base.py)           │
  │  source_id · data_category · tos_compliant · gdpr_basis         │
  │  max_retention_days · available_fields · fetch_profile()        │
  │                                                                   │
  │  ┌──────────────────┐   ┌──────────────────────────────────┐    │
  │  │ SampleAdapter    │   │ (deferred) InstagramGraphAdapter  │    │
  │  │ reads local JSON │   │ ApifyAdapter / PhylloAdapter      │    │
  │  └──────────────────┘   └──────────────────────────────────┘    │
  └──────────┬──────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  Stage 1  INGEST         pipeline/stage1_ingest.py              │
  │  enforce_tos_gate → fetch_profile → build_governance_block      │
  │  → 01-raw.json (validated: 01-raw.schema.json)                  │
  └──────────┬──────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  Stage 2  NORMALIZE      pipeline/stage2_normalize.py           │
  │  assert_within_retention → Profile (Pydantic) → validate        │
  │  → 02-normalized.json (validated: 02-normalized.schema.json)    │
  └──────────┬──────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  Stage 3  FEATURES       pipeline/stage3_features.py            │
  │  Claude API (claude-sonnet-4-6, prompt cache)                   │
  │  → strip_forbidden → assert_demographic_humility                 │
  │  → Art9Scanner.enforce → validate                               │
  │  → 03-features.json (validated: 03-features.schema.json)        │
  └──────────┬──────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  Stage 6  DOSSIER        pipeline/stage6_dossier.py             │
  │  build_scores (EQS + Authenticity + Transparency + Safety)      │
  │  → assert_scores_explainable → build_compliance_flags           │
  │  → gate_art9_report_exposure → assemble → render_report         │
  │  → 06-dossier.json + report.md (validated: 06-dossier.schema)   │
  └─────────────────────────────────────────────────────────────────┘

  Cross-cutting: pipeline/compliance/ subpackage
  (tos, art9, art22, fairness, erasure modules)
```

Every stage is **idempotent** — re-running overwrites only its own artifact.
Compliance annotations are emitted on every stage output, not just the dossier.

## Implementation tracks (dependency-ordered)

### Track A — Schemas & validation plumbing (foundation)

Write the four JSON Schema (draft-7) files:
`01-raw.schema.json`, `02-normalized.schema.json`, `03-features.schema.json`,
`06-dossier.schema.json`. Update `tools/validate.py` to check them against the
JSON Schema meta-schema and confirm they round-trip cleanly.

Key schema contracts:
- `01-raw`: `_governance` block (all 8 fields required), `raw_profile`, `raw_media`.
- `02-normalized`: `handle`, `followers`, `following`, `post_count`, `snapshot_at`,
  `media` array (MediaItem), `governance` block.
- `03-features`: `profile_handle`, `computed_at`, `features` array — every item
  has `feature_id`, `value`, `confidence` [0,1], `method`, `art9_risk`, `signals`.
- `06-dossier`: `dossier_id`, `generated_at`, `profile`, `features` map,
  `scores` map (DossierScore: `value` int [0,100], `signals` list min_length=1,
  `confidence`), `linkage`, `associations`, `compliance_flags`, `provenance`.

**Exit:** `make validate` green; all four schema files pass draft-7 meta-schema;
`tools/validate.py` reports zero errors.

---

### Track B — SourceAdapter ABC + SampleAdapter (parallel with A)

Write `adapters/base.py` — the `SourceAdapter` abstract base class with the full
governance contract (spec §3). Write `adapters/sample.py` — `SampleAdapter` that
reads a local JSON fixture from `projects/<handle>/00-input/sample.json`.

`SampleAdapter` fields:
- `source_id = "sample"`, `data_category = "SAMPLE"`, `tos_compliant = True`
- `auth_type = "NONE"`, `requires_creator_consent = False`
- `calls_per_window = 1000` (effectively unlimited for fixtures)
- `gdpr_basis = "LEGITIMATE_INTERESTS"`, `max_retention_days = 90`

Write a sample fixture at `projects/sample_creator/00-input/sample.json` — a
realistic public Instagram profile JSON with ≥10 media items, ≥2 with #ad or
Paid Partnership tags, and content spanning ≥2 niches.

**Exit:** `from adapters.sample import SampleAdapter; a = SampleAdapter(); a.fetch_profile("sample_creator")` returns a dict with the full governance contract; fixture file exists and loads without error.

---

### Track C — pipeline/compliance/ subpackage (parallel with A, B)

Write `pipeline/compliance/` with modules: `tos.py`, `art9.py`, `art22.py`,
`fairness.py`, `erasure.py`, `__init__.py` (re-exports public API).

Key functions (see spec §9 for full signatures):
- `tos.py`: `enforce_tos_gate(adapter)`, `build_governance_block(...)`,
  `assert_governance_complete(gov)`
- `art9.py`: `Art9Scanner` class — `scan_feature`, `sweep`, `enforce`
  (re-asserts `art9_risk=True` as defense-in-depth over LLM output)
- `art22.py`: `art22_applies(scores)`, `build_compliance_flags(...)`,
  `assert_scores_explainable(scores)`, `gate_art9_report_exposure(...)`
- `fairness.py`: `strip_forbidden_features(features)`,
  `assert_demographic_inference_humility(features)`
- `erasure.py`: `erase_profile(handle, *, dry_run, projects_root)` → `ErasureReceipt`;
  `is_expired(retention_expires_at)`, `assert_within_retention(governance, handle)`,
  `gc_sweep(projects_root)` — path-traversal guard on every erasure call

**Exit:** `from pipeline.compliance import enforce_tos_gate, Art9Scanner, build_compliance_flags, erase_profile` imports cleanly; all functions exist with correct signatures.

---

### Track D — Stage 1 INGEST (depends on A, B, C)

Write `pipeline/stage1_ingest.py`. Orchestrates:
1. `enforce_tos_gate(adapter)` — raises `TosComplianceError` if non-compliant
2. `adapter.fetch_profile(handle)` + `adapter.fetch_media(handle, limit=20)`
3. `build_governance_block(adapter, subject_jurisdiction=..., ingested_at=utcnow)`
4. Assembles raw record, validates against `01-raw.schema.json`
5. Atomic write (`*.tmp` → `os.replace`) to `projects/<handle>/01-raw.json`

**Exit:** `python3 profile_analyst.py --handle sample_creator --stage 1` produces
a schema-valid `01-raw.json` with all 8 governance fields; re-running produces an
identical file (idempotent modulo `ingested_at`).

---

### Track E — Stage 2 NORMALIZE (depends on D)

Write `pipeline/stage2_normalize.py` and `pipeline/models.py` (shared Pydantic models:
`Profile`, `MediaItem`, `GovernanceBlock`, `AudienceSummary`).

Orchestrates:
1. `assert_within_retention(gov, handle)` — refuses expired artifacts
2. Deserialize raw_profile + raw_media → `Profile` (Pydantic v2 validation)
3. Validate against `02-normalized.schema.json`
4. Atomic write to `projects/<handle>/02-normalized.json`

**Exit:** `--stage 2` on a valid `01-raw.json` produces a schema-valid
`02-normalized.json`; A6 idempotency test passes (re-running stage 2 does not
touch `01-raw.json`).

---

### Track F — Stage 3 FEATURES (depends on E)

Write `pipeline/stage3_features.py` and `prompts/stage3-features.md`.

Orchestrates:
1. Compute deterministic features (§5.1–§5.2: ER variants, posting cadence,
   follower/following ratio, tier, `follower_tier`)
2. Build Claude API prompt (system: spec §5 + `stage3-features.md`; user: normalized JSON)
   with prompt caching on system message (`anthropic-beta: prompt-caching-2024-07-31`)
3. Parse LLM JSON response → feature list
4. `strip_forbidden_features` + `assert_demographic_humility` + `Art9Scanner.enforce`
5. Validate against `03-features.schema.json`
6. Atomic write to `projects/<handle>/03-features.json`

`stage3-features.md` prompt:
- Instructs Claude to emit `primary_niche` (taxonomy from spec §5.3), `secondary_niches`,
  `brand_affinity_signals`, `caption_sentiment`, sponsored classification
- Forbidden: binary_gender, ethnicity, race
- Output format: JSON array matching `03-features.schema.json`

**Exit:** A3 (ER exact match), A4 (≥1 sponsored detected), A5 (niche confidence ≥ 0.5),
A9 (Art.9 features flagged) all pass on the sample fixture.

---

### Track G — Stage 6 DOSSIER (depends on F)

Write `pipeline/stage6_dossier.py`. Pure scoring functions + orchestrator:
- `score_engagement_quality`, `score_authenticity`, `score_sponsorship_transparency`,
  `score_brand_safety` — all scoring weights in named `*_WEIGHTS` dicts
- `build_scores(feats)` — calls all four scorers
- `build_compliance_flags(...)` — calls `art22.build_compliance_flags`
- `assemble(...)` → `Dossier` Pydantic model → validated against `06-dossier.schema.json`
- `render_report(dossier)` → `report.md` — pure f-string builder, no Jinja dep
- Atomic write of both `06-dossier.json` and `report.md`

Scoring constants in module (parameterizable, testable):
```python
TIER_BENCHMARK_ER = {Nano:11.5, Micro:4.4, Mid:0.73, Macro:1.02, Mega:1.10, Celebrity:1.20}
EQS_WEIGHTS = {"er": 0.40, "comments": 0.20, "consistency": 0.20, "ratio": 0.20}
```

**Exit:** A2 (full pipeline produces schema-valid artifacts), A8 (every score has
non-empty signals list; compliance_flags present); idempotency test passes
(re-running stage 6 produces identical scores, strips `generated_at`/`dossier_id`).

---

### Track H — CLI orchestrator + tests (depends on A–G)

Write `profile_analyst.py` — the CLI entry point:
- `--handle <handle> --stage all|1,2,3,6` — dispatches to stage modules
- `--allow-noncompliant` — sets `ALLOW_NONCOMPLIANT=true` in env
- `--expose-art9` — passes `expose_art9=True` to report renderer
- `erase --handle <handle> [--dry-run]` — calls `erase_profile`
- `gc` — calls `gc_sweep`

Write `tests/`:
- `tests/compliance/test_tos.py` — A7 (governance complete, ToS gate)
- `tests/compliance/test_art9.py` — A9 (Art.9 scanner, each category)
- `tests/compliance/test_fairness.py` — forbidden feature drop, demographic humility
- `tests/compliance/test_erasure.py` — erase idempotency, path-traversal guard
- `tests/test_stage1.py`, `test_stage2.py`, `test_stage3.py`, `test_stage6.py`
- `tests/test_pipeline_end_to_end.py` — A2 full pipeline, A6 idempotency

Write `tests/fixtures/` — hand-crafted JSON artifacts for each stage boundary.

**Exit:** `make test` green; all A1–A9 acceptance criteria pass; `make run HANDLE=sample_creator` completes end-to-end without error.

---

**Dependency graph:** A, B, C (parallel) → D → E → F → G → H.

## Risks

- **Claude API availability in CI.** Stage 3 calls the Claude API; tests must work without live API.
  *Mitigation:* fixture-based tests mock the Claude call; a separate `--integration` test flag
  calls live API. Unit tests only use fixtures.

- **Instagram data access.** No official API path exists for third-party public profiles.
  *Mitigation:* v1 uses `SampleAdapter` + local fixtures only; live adapters deferred to v2;
  compliance posture documented in CLAUDE.md.

- **WEQS/LLM judge rate limits.** Ensemble calls hit 429s frequently.
  *Mitigation:* v1 build does not depend on ensemble; already documented in spec history.

- **Scoring formula instability.** ER benchmarks (ClickAnalytic Dec 2025) are a snapshot.
  *Mitigation:* benchmarks are named constants, not hardcoded; can be updated per data source.

## Open implementation questions

- **`pipeline/models.py` vs inline models.** Shared Pydantic models could live in `models.py`
  (referenced by multiple stages) or be duplicated per stage. *Default:* shared `models.py`.

- **Fixture data source.** The `sample_creator` fixture needs a realistic but privacy-safe
  profile. *Default:* hand-crafted synthetic JSON matching a mid-tier lifestyle influencer.
