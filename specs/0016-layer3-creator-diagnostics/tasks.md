# Tasks 0016 — Layer 3 Creator Diagnostics

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A and B can be done in parallel. C depends on A. D depends on A+B+C.
E depends on D. F depends on D+E.
**No LLM call. No new external dependencies. Purely additive.**

---

## Track A — Pydantic models + schema contract

- [ ] T1 Add `from typing import Literal` to the existing `from typing import Any` import line
      in `pipeline/models.py`.
- [ ] T2 Append Layer 3 models to `pipeline/models.py` after the `Dossier` class and before
      the `# ── Linkage models` section. Models required:
      - `TopicEntry`: `topic` (str), `share` (float 0–1), `evidence_media_ids` (list[str])
      - `ThemeMix`: `values` (dict[str, float]), `unmapped_ratio` (float 0–1), `confidence`
        (float 0–1), `method: Literal["heuristic"] = "heuristic"`, `version: str = "v1"`
      - `ContentFormatMix`: `values` (dict[str, float]), `method: Literal["computed"] = "computed"`
      - `EditorialConsistencyScore`: `value` (int 0–100), `method: Literal["heuristic"] = "heuristic"`
      - `ContentAnalysis`: optional fields `theme_mix`, `top_topics`, `editorial_consistency_score`,
        `content_format_mix`
      - `DerivedInsights`: `computed_at` (str), `content_analysis` (ContentAnalysis)
      - `LabeledInterpretation`: `value` (str), `confidence` (float 0–1), `method` (str),
        `version` (str = "v1"), `evidence` (list[str]), `matched_rule` (str | None)
      - `BrandFitEntry`: `category` (str), `fit: Literal["high","medium","low"]`,
        `confidence` (float 0–1), `method: Literal["rule_based"] = "rule_based"`
      - `RiskFlag`: `flag` (str), `severity: Literal["high","medium","low"]`,
        `method: Literal["rule_based","score_derived"] = "rule_based"`, `evidence` (list[str])
      - `CreatorSizeField`: `value` (str), `method: Literal["computed"] = "computed"`
      - `DerivedDiagnostics`: `computed_at` (str), `creator_archetype` (LabeledInterpretation),
        `creator_size` (CreatorSizeField), `lifecycle_stage` (LabeledInterpretation),
        `sponsorship_readiness` (LabeledInterpretation), `brand_fit` (list[BrandFitEntry]),
        `risk_flags` (list[RiskFlag])
- [ ] T3 Add optional `derived_insights: dict[str, Any] | None = None` and
      `derived_diagnostics: dict[str, Any] | None = None` fields to the `Dossier` model.
- [ ] T4 Update `schemas/06-dossier.schema.json`: add optional `derived_insights` and
      `derived_diagnostics` to `"properties"` (not to `"required"`). `derived_diagnostics`
      property should enumerate its known sub-properties. Do not use `additionalProperties: false`
      at the top level of these blocks (they will evolve).
- [ ] T5 Confirm `make validate` passes with the updated schema.

**Exit (Track A):** `make validate` green; `Dossier` model accepts the two new optional fields;
model tests for `TopicEntry`, `ThemeMix`, `BrandFitEntry`, `RiskFlag` pass (confidence
out-of-range raises `ValidationError`; invalid `fit` enum raises `ValidationError`).

---

## Track B — Content analysis (parallel with A)

- [ ] T6 Create `pipeline/diagnostics.py`. Add module docstring referencing spec 0016 §6.1.
      Add module-level constants: `_NOISE_TAGS` (frozenset of generic engagement hashtags),
      `_STOP_WORDS` (frozenset of common English stop words for caption parsing),
      `_HASHTAG_THEME` (dict[str, str] — full lookup table from spec §6.1 table).
- [ ] T7 Implement `compute_content_format_mix(media_items: list[dict]) -> ContentFormatMix | None`.
      Returns `None` for empty input. Keys lowercased. Values normalized (sum = 1.0).
      Method is `"computed"` — no confidence field.
- [ ] T8 Implement `compute_theme_mix(media_items: list[dict]) -> ThemeMix | None`.
      Returns `None` for empty input. Filters noise hashtags before counting.
      `unmapped_ratio = unmapped_count / total_non_noise_count` (0.0 when no non-noise hashtags).
      `confidence = 1.0 - unmapped_ratio`. `values[theme]` = posts with ≥1 mapped hashtag / total_posts.
- [ ] T9 Implement `compute_editorial_consistency(theme_mix: ThemeMix | None) -> EditorialConsistencyScore | None`.
      Returns `None` when `theme_mix` is None. Score = `int(round(max_concentration × mapped_ratio × 100))`.
      Clamped 0–100. Method is `"heuristic"` — no confidence field on the score object itself
      (confidence is already on `theme_mix`).
- [ ] T10 Implement `compute_top_topics(media_items: list[dict], top_n: int = 10) -> list[TopicEntry]`.
      Combine lowercase hashtags (filtered by noise blocklist, len ≥ 3) and caption words
      (≥4 chars, filtered by stop words). Build `topic_posts: dict[str, set[str]]` keyed by token,
      valued by set of media_ids. `share = |post_ids| / total_posts`. Sort by share descending.
      `evidence_media_ids = sorted(post_ids)[:5]` — stable sort, capped at 5.

**Exit (Track B):** unit tests for all four functions pass:
- `compute_content_format_mix([])` → `None`
- `compute_content_format_mix` normalizes correctly and lowercases keys
- `compute_theme_mix` maps known hashtags; tracks `unmapped_ratio`
- `compute_editorial_consistency(None)` → `None`
- high thematic concentration → high editorial score; high unmapped_ratio → lower score
- `compute_top_topics` excludes noise; uses evidence_media_ids; most-frequent-first order
- `compute_top_topics` uses captions + hashtags (caption word appears in results)

---

## Track C — Diagnostic classifiers (depends on A)

- [ ] T11 Add to `pipeline/diagnostics.py`: niche taxonomy constants `_PROFESSIONAL_NICHES`,
      `_ENTERTAINMENT_NICHES`, `_LIFESTYLE_NICHES` (frozensets matching spec §6.2).
- [ ] T12 Implement `classify_creator_archetype(niche, niche_conf, freq, editorial_consistency,
      commercial_ratio, er_vs_benchmark_ratio) -> LabeledInterpretation`.
      Priority-ordered rules as per spec §6.2 table. Each rule sets `value`, `matched_rule`,
      `evidence`, and `confidence = niche_conf × rule_weight` (capped at 0.95).
      Fallback rule always fires for non-matching niches.
- [ ] T13 Implement `classify_creator_size(tier: str) -> CreatorSizeField`. Pure lookup from
      `_TIER_TO_SIZE` dict. No confidence field.
- [ ] T14 Implement `classify_lifecycle_stage(tier, consistency, er_vs_benchmark_ratio)
      -> LabeledInterpretation`. Base from `_TIER_TO_LIFECYCLE_BASE`; apply ER override
      (`< 0.5× benchmark → plateaued`) and Micro-stalled override (`consistency < 0.3 → nascent`).
      Confidence degrades when ER or consistency data missing (spec §6.4).
- [ ] T15 Add `_FTC_SCORE` dict and implement `compute_sponsorship_readiness(ftc_status, auth_score,
      brand_safety_score, consistency) -> LabeledInterpretation`. Hard `at_risk` override first.
      Weighted formula per spec §6.5. Confidence formula: `0.55 + 0.30×(auth/100) + 0.15×(brand/100)`,
      capped at 0.95.
- [ ] T16 Add `_BrandFitDef` dataclass and `_NICHE_BRAND_FIT` lookup dict. Implement
      `compute_brand_fit(primary_niche, primary_niche_conf, secondary_niches) -> list[BrandFitEntry]`.
      Primary niche at full multiplier; secondary niches at ×0.60 discount. One entry per category;
      highest confidence wins. Sorted descending by confidence.
- [ ] T17 Implement `compute_risk_flags(tier, pod_signal, ftc_status, brand_safety_score,
      auth_score, engagement_anomaly, freq) -> list[RiskFlag]`.
      All 8 flags from spec §6.7 table. Each flag is independent; multiple can fire.
      Each `RiskFlag` carries `flag`, `severity`, `method`, `evidence` with ≥1 evidence token.

**Exit (Track C):** unit tests for all six classifiers pass:
- archetype: professional+high_consistency → specialist_educator; matched_rule present
- archetype: high_commercial_ratio → brand_builder regardless of niche
- archetype: confidence scales with niche_conf; fallback returns content_creator
- creator_size: Micro → micro; method = "computed"
- lifecycle: plateau override fires when ER < 0.5× benchmark; evidence present
- lifecycle: Micro + consistency < 0.3 → nascent (stalled)
- sponsorship_readiness: ftc=at_risk always returns low with matched_rule=low_v1_ftc_override
- sponsorship_readiness: high scores produce high readiness
- brand_fit: known niche → entries; sorted by confidence; fit field present
- brand_fit: unknown niche → empty list
- risk_flags: all 8 flags fire under correct conditions; each has ≥1 evidence token
- risk_flags: clean profile (Mid, ftc=compliant, no anomalies, freq=3) → at most ftc=compliant-related flag

---

## Track D — Orchestrators + Stage 6 wiring (depends on A+B+C)

- [ ] T18 Add `_now_utc() -> str` helper to `pipeline/diagnostics.py`.
      Implement `build_derived_insights(media_items, feats) -> DerivedInsights`.
      Calls `compute_theme_mix`, `compute_editorial_consistency`, `compute_top_topics`,
      `compute_content_format_mix`. Sets `computed_at = _now_utc()`.
- [ ] T19 Implement `build_derived_diagnostics(feats, scores, insights, tier, niche, niche_conf,
      secondary_niches, freq, consistency, ftc_status, pod_signal, engagement_anomaly, followers)
      -> DerivedDiagnostics`. Computes `er_vs_benchmark_ratio` from `er_by_followers` and
      `TIER_BENCHMARK_ER`. Computes `commercial_ratio` from `sponsored_posts` and
      `likely_sponsored_undisclosed` features. Extracts `auth_score` and `brand_safety_score`
      from the `scores` dict. Calls all six classifiers. Sets `computed_at = _now_utc()`.
- [ ] T20 In `stage6_dossier.run()`, after `scores = build_scores(feats)`, extract the values
      needed for diagnostics from `normalized` and `feats` (see spec §4 table). Call
      `build_derived_insights(media_items, feats)` and `build_derived_diagnostics(...)`.
- [ ] T21 In `stage6_dossier.run()`, add to `dossier_dict`:
      `dossier_dict["derived_insights"] = derived_insights.model_dump()`
      `dossier_dict["derived_diagnostics"] = derived_diagnostics.model_dump()`
      before the `jsonschema.validate` call. Confirm schema validation still passes.

**Exit (Track D):** running `python3 profile_analyst.py --handle sample_creator --stage 6`
produces `06-dossier.json` with both blocks present. `make validate` green.
Integration test: `06-dossier.json` contains `derived_insights.content_analysis` and
`derived_diagnostics.creator_archetype`.

---

## Track E — Report rendering (depends on D)

- [ ] T22 Add label→display maps to `pipeline/stage6_dossier.py` (before `render_report`):
      `_ARCHETYPE_DISPLAY`, `_LIFECYCLE_DISPLAY`, `_READINESS_DISPLAY`, `_SEVERITY_DISPLAY`.
      Each maps a label string to a `(display_title, one_sentence_description)` tuple.
      No interpretive language; descriptions are factual summaries.
- [ ] T23 Implement `_render_diagnostics_section(derived_insights, derived_diagnostics) -> str`.
      Renders: Creator Archetype (title + description + evidence/rule/confidence line),
      Lifecycle Stage (title + description + size/confidence line),
      Sponsorship Readiness (title + description),
      Brand Fit (high-fit list + medium-fit list),
      Risk Assessment (markdown table: Risk | Severity).
      Closes with the advisory note: "All diagnostics are derived labels, not facts."
      Returns `""` when `derived_diagnostics` is None.
- [ ] T24 Add `derived_insights=None` and `derived_diagnostics=None` keyword parameters to
      `render_report()`. Call `_render_diagnostics_section(derived_insights, derived_diagnostics)`
      and append the result after `platform_section`.
- [ ] T25 Update the `render_report` call in `stage6_dossier.run()` to pass:
      `derived_insights=derived_insights, derived_diagnostics=derived_diagnostics`.

**Exit (Track E):** `report.md` contains all five diagnostic sub-sections.
Sections are absent (report identical to pre-spec behavior) when `derived_diagnostics` is None.

---

## Track F — Tests (depends on D+E)

- [ ] T26 Create `tests/test_diagnostics.py`. Add unit test classes for each compute function
      (format_mix, theme_mix, editorial_consistency, top_topics) and each classifier
      (archetype, creator_size, lifecycle_stage, sponsorship_readiness, brand_fit, risk_flags).
      Acceptance criteria A4, A5, A6, A7, A8, A9, A10, A14 each require ≥1 test case.
- [ ] T27 Add `TestOrchestrators` class to `tests/test_diagnostics.py`. Test that
      `build_derived_insights` returns `DerivedInsights` and `build_derived_diagnostics`
      returns `DerivedDiagnostics` for a minimal media + feature fixture. Verify `computed_at`
      is a non-empty ISO string.
- [ ] T28 Add `TestDerivedDiagnosticsInDossier` class to `tests/test_stage6.py`. Using the
      existing `project_with_stages` fixture, assert that the produced `06-dossier.json`
      contains `derived_insights` and `derived_diagnostics` with the expected top-level keys.
- [ ] T29 Add `TestDiagnosticsInReport` class to `tests/test_stage6.py`. Assert that `report.md`
      produced by `run()` contains "Creator Archetype", "Lifecycle Stage", "Brand Fit",
      "Risk", and "Sponsorship Readiness".
- [ ] T30 Run `make test` and confirm all tests pass. Run `make validate` and confirm green.
      No pre-existing test may be broken.

**Exit (Track F):** `make test` green; `make validate` green; all 15 acceptance criteria from
`metadata.yml` are covered by at least one test.
