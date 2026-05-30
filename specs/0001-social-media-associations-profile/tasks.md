# Tasks 0001 — Social-Media Associations Profile: Instagram-Seeded Unified Creator Dossier

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A, B, C can be done in parallel. D depends on A+B+C; E on D; F on E; G on F; H on A–G.

---

## Track A — Schemas & validation plumbing

- [ ] T1 Write `schemas/01-raw.schema.json` (draft-7). Required fields: `handle`, `platform`,
      `_governance` (all 8 sub-fields required), `raw_profile` (object), `raw_media` (array).
- [ ] T2 Write `schemas/02-normalized.schema.json`. Required: `handle`, `followers`, `following`,
      `post_count`, `snapshot_at` (ISO datetime), `media` (array of MediaItem objects), `governance`.
- [ ] T3 Write `schemas/03-features.schema.json`. Required: `profile_handle`, `computed_at`,
      `features` (array). Each Feature item: `feature_id` (string), `value`, `confidence` [0,1],
      `method` (enum: computed|inferred|llm), `art9_risk` (bool), `signals` (array, minItems 1).
- [ ] T4 Write `schemas/06-dossier.schema.json`. Required: `dossier_id`, `generated_at`, `profile`,
      `features` (map keyed by feature_id), `scores` (map — each score: `value` int [0,100],
      `signals` array min 1, `confidence`), `linkage`, `associations`, `compliance_flags`, `provenance`.
- [ ] T5 Update `tools/validate.py` to load and validate each schema against JSON Schema meta-schema
      (draft-7). Add `validate_schemas()` to check all `schemas/*.schema.json`.
- [ ] T6 Verify `make validate` green with all four schemas present. Write a smoke test:
      `python3 tools/validate.py` exits 0.

**Exit (Track A):** `make validate` green; all four `.schema.json` files pass draft-7
meta-schema; `tools/validate.py` reports zero errors including `metadata.yml`.

---

## Track B — SourceAdapter ABC + SampleAdapter

- [ ] T7 Write `adapters/base.py` — `SourceAdapter` ABC with the full governance contract
      (spec §3): `source_id`, `data_category`, `tos_compliant`, `auth_type`,
      `requires_creator_consent`, `calls_per_window`, `window_seconds`, `available_fields`,
      `estimated_fields`, `gdpr_basis`, `requires_lia`, `max_retention_days`, `deletion_on_request`.
      Abstract methods: `fetch_profile(handle: str) -> dict`, `fetch_media(handle, limit) -> list`.
- [ ] T8 Write `adapters/sample.py` — `SampleAdapter(SourceAdapter)` that reads
      `projects/<handle>/00-input/sample.json` and returns the profile + media list.
      Fields: `source_id="sample"`, `data_category="SAMPLE"`, `tos_compliant=True`,
      `gdpr_basis="LEGITIMATE_INTERESTS"`, `max_retention_days=90`.
- [ ] T9 Create `projects/sample_creator/00-input/sample.json` — synthetic fixture: a
      mid-tier lifestyle influencer with 45,000 followers, ≥10 media items, ≥2 with explicit
      `#ad` or `is_paid_partnership: true`, content spanning Lifestyle + Fitness niches,
      realistic engagement counts (ER ~3–5%), mix of feed posts, Reels, and carousels.

**Exit (Track B):** `SampleAdapter().fetch_profile("sample_creator")` returns a dict;
fixture loads without error; all governance fields present on the adapter.

---

## Track C — pipeline/compliance/ subpackage

- [ ] T10 Create `pipeline/compliance/__init__.py` — re-exports:
       `enforce_tos_gate`, `build_governance_block`, `assert_governance_complete`,
       `Art9Scanner`, `build_compliance_flags`, `assert_scores_explainable`,
       `gate_art9_report_exposure`, `strip_forbidden_features`,
       `assert_demographic_inference_humility`, `erase_profile`, `is_expired`,
       `assert_within_retention`, `gc_sweep`, `TosComplianceError`, `ComplianceError`.
- [ ] T11 Write `pipeline/compliance/tos.py`:
       - `TosComplianceError(source_id, data_category)` — names exact variable, actionable message
       - `allow_noncompliant()` — reads `ALLOW_NONCOMPLIANT` env var; exact `"true"` match only
       - `enforce_tos_gate(adapter)` — raises `TosComplianceError` or passes
       - `build_governance_block(adapter, *, subject_jurisdiction, consent_record_id, ingested_at)`
         → dict with all 8 fields; `retention_expires_at = ingested_at + max_retention_days`
       - `assert_governance_complete(gov)` — checks `REQUIRED_GOVERNANCE_FIELDS`
- [ ] T12 Write `pipeline/compliance/art9.py`:
       - `Art9Category` enum (HEALTH, SEXUALITY, RELIGION, POLITICAL)
       - `ART9_SENSITIVE_FEATURE_IDS` set — feature_ids that are categorically Art.9-adjacent
       - `ART9_NICHE_VALUES` dict — niche value strings per category (case-insensitive match)
       - `ART9_TEXT_PATTERNS` dict — compiled regex per category for value/notes scanning
       - `Art9Finding` dataclass — `feature_id`, `categories`, `reason`
       - `Art9Scanner.scan_feature(feature)` → `Art9Finding | None`
       - `Art9Scanner.sweep(features)` → `list[Art9Finding]`
       - `Art9Scanner.enforce(features)` → `list[str]` (forces `art9_risk=True`, returns ids)
- [ ] T13 Write `pipeline/compliance/art22.py`:
       - `SELECTION_SCORES` — set of campaign-affecting score names
       - `art22_applies(scores)` → bool
       - `assert_scores_explainable(scores)` — raises `ComplianceError` if empty signals
       - `build_compliance_flags(*, governance, scores, art9_feature_ids, ftc_disclosure_status, handle)` → dict
       - `gate_art9_report_exposure(art9_ids, *, expose_art9)` → list[str]
- [ ] T14 Write `pipeline/compliance/fairness.py`:
       - `FORBIDDEN_FEATURE_IDS` set — binary_gender, ethnicity, race, race_ethnicity, etc.
       - `ALLOWED_DEMOGRAPHIC` set — audience_gender_skew, age_group (continuous/inferred only)
       - `strip_forbidden_features(features)` → `(kept: list, dropped: list[str])`
       - `assert_demographic_inference_humility(features)` — raises if demographic feature
         has `confidence >= 1.0` or `method != "inferred"`
- [ ] T15 Write `pipeline/compliance/erasure.py`:
       - `ErasureReceipt` dataclass — `handle`, `erased_at`, `artifacts_deleted`, `bytes_freed`, `existed`
       - `_safe_handle(handle)` — path-traversal guard: rejects `/`, `..`, absolute paths
       - `erase_profile(handle, *, dry_run, projects_root)` → `ErasureReceipt`; idempotent
       - `is_expired(retention_expires_at, *, now)` → bool
       - `assert_within_retention(governance, *, handle, auto_erase)` → None or raises
       - `gc_sweep(projects_root)` → list[ErasureReceipt]

**Exit (Track C):** `from pipeline.compliance import enforce_tos_gate, Art9Scanner,
build_compliance_flags, erase_profile` all import cleanly; all functions have correct signatures.

---

## Track D — Stage 1 INGEST

- [ ] T16 Write `pipeline/stage1_ingest.py`:
       - `run(handle, adapter, project_dir)` → Path
       - Step 1: `enforce_tos_gate(adapter)`
       - Step 2: `adapter.fetch_profile(handle)` + `adapter.fetch_media(handle, limit=20)`
       - Step 3: `build_governance_block(adapter, subject_jurisdiction=..., ingested_at=utcnow)`
       - Step 4: assemble raw record dict + validate against `01-raw.schema.json`
       - Step 5: atomic write `01-raw.json` (`.tmp` → `os.replace`)
       - Infer `subject_jurisdiction` from `profile.get("location") or "UNKNOWN"`
- [ ] T17 Wire `--stage 1` in `profile_analyst.py` → `stage1_ingest.run(handle, SampleAdapter(), ...)`

**Exit (Track D):** `--stage 1 --handle sample_creator` writes schema-valid `01-raw.json`
with all 8 governance fields; re-running produces identical file.

---

## Track E — Stage 2 NORMALIZE

- [ ] T18 Write `pipeline/models.py` — shared Pydantic v2 models:
       - `GovernanceBlock` (all 8 governance fields, types validated)
       - `MediaItem` (media_id, media_type, posted_at, likes, comments, saves, shares,
         views, caption, hashtags, mentions, is_paid_partnership, paid_partner_handle)
       - `Profile` (handle, platform, profile_id, display_name, bio, website, is_verified,
         is_business, account_type, followers, following, post_count, snapshot_at,
         media: list[MediaItem], audience: None, governance: GovernanceBlock)
- [ ] T19 Write `pipeline/stage2_normalize.py`:
       - `run(handle, project_dir)` → Path
       - Step 1: load `01-raw.json`; `assert_within_retention(gov, handle)`
       - Step 2: `assert_governance_complete(gov)`
       - Step 3: parse raw_profile + raw_media → `Profile` (Pydantic validation)
       - Step 4: validate against `02-normalized.schema.json`
       - Step 5: atomic write `02-normalized.json`
- [ ] T20 Wire `--stage 2` in `profile_analyst.py`

**Exit (Track E):** A6 passes — re-running stage 2 does not modify `01-raw.json`;
`02-normalized.json` is schema-valid with all Profile fields populated.

---

## Track F — Stage 3 FEATURES

- [ ] T21 Write `prompts/stage3-features.md` — Claude system prompt:
       - Instructs Claude to analyze captions/hashtags and return a JSON array of feature objects
       - Taxonomy: Lifestyle, Beauty/Makeup, Fashion, Fitness/Health, Food/Cooking, Travel,
         Tech/Gaming, Finance, Parenting, Pets, Sustainability, Sports, Entertainment,
         Education, Business/Entrepreneurship, Other
       - Sponsored detection: explicit signals (#ad, Paid Partnership) + classification of
         remaining posts as commercial/non-commercial with confidence
       - Forbidden output: binary_gender, ethnicity, race, any feature_id in FORBIDDEN_FEATURE_IDS
       - Output format: JSON array matching 03-features.schema.json Feature schema
- [ ] T22 Write `pipeline/stage3_features.py`:
       - `run(handle, project_dir, *, anthropic_client)` → Path
       - Step 1: load `02-normalized.json`; `assert_within_retention(gov, handle)`
       - Step 2: compute deterministic features (ER by followers, tier, posting cadence,
         consistency score, follower/following ratio, hashtag fingerprint, content language)
       - Step 3: build Claude prompt (system = stage3-features.md with cache_control;
         user = relevant normalized JSON fields)
       - Step 4: call `claude-sonnet-4-6` with prompt caching; parse JSON response
       - Step 5: merge deterministic + LLM features; `strip_forbidden_features`;
         `assert_demographic_humility`; `Art9Scanner().enforce`
       - Step 6: validate against `03-features.schema.json`
       - Step 7: atomic write `03-features.json`
- [ ] T23 Write `pipeline/scoring_utils.py` — shared scoring primitives:
       `clamp(x, lo, hi)`, `er_vs_benchmark(er, tier)`, `_ratio_reasonableness(ratio)`,
       `TIER_BENCHMARK_ER`, `EQS_WEIGHTS`, `AUTH_WEIGHTS`
- [ ] T24 Wire `--stage 3` in `profile_analyst.py`; load `ANTHROPIC_API_KEY` from env

**Exit (Track F):** A3 (ER exact match on fixture), A4 (≥1 sponsored detected), A5
(niche confidence ≥ 0.5, method: llm), A9 (Art.9 features flagged) — all pass
on `sample_creator` fixture.

---

## Track G — Stage 6 DOSSIER

- [ ] T25 Write `pipeline/stage6_dossier.py`:
       - `run(handle, project_dir, *, pipeline_version, expose_art9)` → Path
       - `index_features(features_doc)` → `dict[str, dict]`
       - `score_engagement_quality(feats)` → `DossierScore` (uses `EQS_WEIGHTS`, `TIER_BENCHMARK_ER`)
       - `score_authenticity(feats)` → `DossierScore` (50-pt neutral baseline + penalties)
       - `score_sponsorship_transparency(feats)` → `DossierScore`
       - `score_brand_safety(feats)` → `DossierScore`
       - `build_scores(feats)` → `dict[str, DossierScore]`
       - `build_compliance_flags(...)` → calls `art22.build_compliance_flags`
       - `assemble(...)` → `Dossier` Pydantic model
       - `render_report(dossier, *, expose_art9)` → str (7 sections per spec §8)
       - Atomic write of both `06-dossier.json` and `report.md`
- [ ] T26 Add `DossierScore`, `ComplianceFlags`, `Provenance`, `Dossier` Pydantic models
       to `pipeline/models.py`. `DossierScore.signals` has `min_length=1`.
- [ ] T27 Wire `--stage 6` in `profile_analyst.py`

**Exit (Track G):** A2 (full pipeline schema-valid), A8 (every score has non-empty
signals, compliance_flags present); idempotency test: re-run produces identical scores
(modulo `generated_at`/`dossier_id`).

---

## Track H — CLI orchestrator + full test suite

- [ ] T28 Write final `profile_analyst.py` with all subcommands:
       `--stage all|1,2,3,6`, `erase --handle`, `gc`, `--allow-noncompliant`, `--expose-art9`
- [ ] T29 Write `tests/compliance/test_tos.py` — A7: governance fields complete;
       ToS gate rejects mock non-compliant adapter; exact-`"true"`-only bypass
- [ ] T30 Write `tests/compliance/test_art9.py` — A9: each Art.9 category detected;
       health niche forces `art9_risk=True` even when LLM said False;
       non-sensitive niche not flagged; text-lexicon scan catches notes field
- [ ] T31 Write `tests/compliance/test_fairness.py` — binary_gender dropped;
       ethnicity dropped; audience_gender_skew allowed; demographic with confidence=1.0 rejected
- [ ] T32 Write `tests/compliance/test_erasure.py` — erase deletes dir; erase idempotent;
       path-traversal guard; retention expired raises; within-retention passes
- [ ] T33 Write `tests/test_stage1.py`, `tests/test_stage2.py` — unit tests for
       each stage's orchestration logic using fixture files
- [ ] T34 Write `tests/test_stage3.py` — A3 (ER exact), A4 (sponsored detected),
       A5 (niche ≥0.5), A9 (Art.9 flagged); Claude API mocked via fixture response
- [ ] T35 Write `tests/test_stage6.py` — A8 (scores explainable); scoring math
       locked (exact EQS at benchmark → er_component == 50; pod penalty exactly −20);
       `DossierScore(signals=[])` raises `ValidationError`; schema-validity test
- [ ] T36 Write `tests/test_pipeline_end_to_end.py` — A2 full pipeline run;
       A6 idempotency (re-run stage 2 does not touch `01-raw.json`)
- [ ] T37 Write `tests/fixtures/` — hand-crafted JSON for each stage boundary:
       `01-raw.json`, `02-normalized.json`, `03-features.json` (complete + sparse variants)
- [ ] T38 Confirm `make test` green; `make validate` green; `make run HANDLE=sample_creator` completes

**Exit (Track H):** All acceptance criteria A1–A9 pass; `make test` green;
`make run HANDLE=sample_creator` produces `06-dossier.json` + `report.md` end-to-end.

---

**Total: ~38 tasks** across 8 tracks (Tracks A–C parallel; D→E→F→G→H sequential).

## Out of scope (do not include in v1 build)

- Stage 4 LINKAGE (`UILinker`, `pipeline/linkage/`, `04-linkage.schema.json`) — deferred to v3.
- Stage 5 ASSOCIATIONS (graph engine, Leiden clustering, `05-graph.schema.json`) — deferred to v2.
- Live Instagram adapters (Graph API, Apify, Phyllo) — deferred to v2.
- Audience demographics (creator-consented OAuth) — deferred to v2.
- Deep fake-follower sampling (follower-list traversal) — deferred to v2.
- Cross-platform identity linkage (UIL, PALE, Fellegi-Sunter) — deferred to v3.
