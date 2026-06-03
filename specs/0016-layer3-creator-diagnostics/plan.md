# Plan 0016 — Layer 3 Creator Diagnostics

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
Adds `derived_insights` and `derived_diagnostics` blocks to Stage 6 by computing
content analysis and interpretive labels from existing Stage 3 features and scores.
Net-new code is confined to `pipeline/diagnostics.py` and targeted additions to
`pipeline/models.py`, `pipeline/stage6_dossier.py`, and `schemas/06-dossier.schema.json`.
**No LLM call. No new external dependencies. Purely additive to existing Stage 6 output.**

## Architecture (reference)

```
02-normalized.json (media[])
         │
         ▼
pipeline/diagnostics.py
         │
         ├─► build_derived_insights()
         │     └── ContentAnalysis
         │           ├── theme_mix          (heuristic — hashtag lookup)
         │           ├── top_topics         (heuristic — captions+hashtags)
         │           ├── editorial_consistency_score  (heuristic — thematic concentration)
         │           └── content_format_mix (computed  — media_type distribution)
         │
03-features.json + scores{}
         │
         └─► build_derived_diagnostics()
               ├── creator_archetype      (rule_based — 6 archetypes)
               ├── creator_size           (computed   — tier mapping)
               ├── lifecycle_stage        (rule_based — tier + ER + consistency)
               ├── sponsorship_readiness  (score_derived — weighted formula)
               ├── brand_fit[]            (rule_based — niche lookup)
               └── risk_flags[]           (rule_based + score_derived — 8 flags)
         │
         ▼
stage6_dossier.run()
         ├─► 06-dossier.json  (derived_insights + derived_diagnostics blocks added)
         └─► report.md        (Creator Diagnostics section added)
```

## Tracks

- **Track A — Pydantic models + schema contract (parallel with B).**
  Add Layer 3 models to `pipeline/models.py`: `TopicEntry`, `ThemeMix`, `ContentFormatMix`,
  `EditorialConsistencyScore`, `ContentAnalysis`, `DerivedInsights`, `LabeledInterpretation`,
  `BrandFitEntry`, `RiskFlag`, `CreatorSizeField`, `DerivedDiagnostics`.
  Update `schemas/06-dossier.schema.json` with optional `derived_insights` and
  `derived_diagnostics` blocks. Confirm `make validate` passes.

- **Track B — Content analysis (parallel with A).**
  Create `pipeline/diagnostics.py` with four pure functions:
  `compute_content_format_mix`, `compute_editorial_consistency`, `compute_top_topics`,
  `compute_theme_mix`. Implements the noise blocklist, hashtag→theme lookup table,
  and `unmapped_ratio` tracking (spec §6.1).

- **Track C — Diagnostic classifiers (depends on A).**
  Add to `pipeline/diagnostics.py`: `classify_creator_archetype`, `classify_creator_size`,
  `classify_lifecycle_stage`, `compute_sponsorship_readiness`, `compute_brand_fit`,
  `compute_risk_flags`. Implements the priority-ordered archetype rules, ER override for
  lifecycle, weighted readiness formula, brand fit lookup table, and 8 independent risk flags
  (spec §6.2–6.7).

- **Track D — Stage 6 wiring (depends on A+B+C).**
  Add `build_derived_insights` and `build_derived_diagnostics` orchestrators to
  `pipeline/diagnostics.py`. Wire both into `stage6_dossier.run()`: serialize to
  `dossier_dict`, validate against updated schema. Add `derived_insights` and
  `derived_diagnostics` optional fields to the `Dossier` Pydantic model.

- **Track E — Report rendering (depends on D).**
  Add `_render_diagnostics_section()` to `pipeline/stage6_dossier.py`. Pass
  `derived_diagnostics` to `render_report()`. Append the Creator Diagnostics section
  (archetype, lifecycle, brand fit, risk assessment, readiness) to `report.md`
  using static label→display maps (no LLM, no prose in JSON).

- **Track F — Tests (depends on D+E).**
  Create `tests/test_diagnostics.py` covering all pure compute functions and orchestrators.
  Extend `tests/test_stage6.py` with integration checks: dossier JSON contains both blocks,
  `report.md` contains all five diagnostic sections, `make test` and `make validate` green.

Tracks A and B can be done in parallel. C depends on A. D depends on A+B+C. E depends on D. F depends on D+E.

## Sequencing & PR boundaries

1. **PR-1 (A):** Pydantic models + schema update. `make validate` green. No behavior change.
2. **PR-2 (B):** `pipeline/diagnostics.py` — content analysis functions + unit tests.
3. **PR-3 (C):** diagnostic classifiers (archetype, size, lifecycle, readiness, brand fit, risk) + unit tests.
4. **PR-4 (D):** orchestrators + Stage 6 wiring — dossier JSON contains both blocks.
5. **PR-5 (E+F):** `render_report` extension + full test suite. `make test` green.

## Risks & mitigations

- **`primary_niche` not in brand fit lookup table.** → `compute_brand_fit` returns `[]`;
  Stage 6 emits an empty list; no error. Add niche to lookup table in the follow-on iteration.
- **`theme_mix.unmapped_ratio` near 1.0.** → `editorial_consistency_score` will be near 0;
  archetype may fall through to `content_creator` fallback. This is correct behavior —
  the data is genuinely sparse. The `unmapped_ratio` field surfaces the drift operationally.
- **Stage 3 feature missing from index.** → All compute functions accept `None` for optional
  inputs and fall back to neutral defaults (e.g., `commercial_ratio = 0`, `freq = None`).
  No crash; confidence degrades proportionally.
- **`editorial_consistency_score` confused with `posting_consistency_score`.** → The two fields
  have distinct `feature_id` / key names and are computed by different functions. Decision D4
  documents the conceptual distinction explicitly; a code comment in `diagnostics.py` will
  point to spec §6.1 to prevent regression.
- **Scope creep toward LLM archetype classification.** → Explicitly deferred per Non-Goals §2;
  `method: rule_based` + `version: v1` in the output flags the field as replaceable when
  an LLM-based classifier is introduced.

## Out of scope (this plan)

LLM-based archetype or brand fit classification, score recalculation from diagnostics,
audience-demographics diagnostics, backfill of existing dossier artifacts,
and any change to Stage 1B / Stage 3 behavior — all deferred per spec §2.
