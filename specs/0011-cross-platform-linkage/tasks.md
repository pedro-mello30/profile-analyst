# Tasks 0011 — Cross-Platform Identity Linkage (Stage 4, v3a)

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A and B can be done in parallel. C depends on A; D depends on A+B+C; E depends on A+D; F integrates all.

---

## Track A — Contract & models

- [ ] T1 Create `schemas/04-linkage.schema.json` (draft-7): top-level `handle`, `method_version`
      (enum `["v3a"]`), preserved `governance` block, and `candidates[]` (array).
- [ ] T2 Define the candidate object in the schema — `platform`, `candidate_handle`, `confidence`
      (number 0–1), `likelihood_ratio` (number), `feature_evidence` (array, `minItems: 1`, items
      `{feature, agreement, detail}`), `classification` (enum `link|possible_link|non_link`),
      `multi_match_flag` (bool), `manual_review_required` (bool), `human_review_status`
      (enum `pending|approved|rejected`), `consent_record_id` (string|null), `surfaceable` (bool);
      mark the required set and `additionalProperties: false`.
- [ ] T3 Register `04-linkage.schema.json` in `tools/validate.py` so `make validate` checks it.
- [ ] T4 Add `LinkageCandidate` and `LinkageDocument` Pydantic v2 models to `pipeline/models.py`
      mirroring the schema (validators: `confidence ∈ [0,1]`, `feature_evidence` non-empty).
- [ ] T5 Unit test: `LinkageDocument` round-trips a hand-written candidate and rejects one with
      empty `feature_evidence` (`tests/linkage/test_models.py`).

**Exit (Track A):** `make validate` green with the new schema; model round-trip + rejection tests pass.

---

## Track B — Cross-platform source + `[uil]` extra

- [ ] T6 Create `adapters/cross_platform/base.py` — `CrossPlatformAdapter(SourceAdapter)` ABC;
      declares the governance class attributes and the `fetch_*` contract for candidate accounts.
- [ ] T7 Create `adapters/cross_platform/sample_uil.py` — `SampleUILAdapter` reading
      `projects/<handle>/00-input/cross_platform.json`; `tos_compliant=True`,
      `data_category="public_profile"`, `requires_creator_consent=True`; reaches no network.
- [ ] T8 Add a committed fixture `projects/<handle>/00-input/cross_platform.json` with a small set
      of candidate accounts across Twitter/X, TikTok, YouTube (mix of strong, weak, and non-matches).
- [ ] T9 Add the optional `[uil]` extra to `pyproject.toml` (`imagehash`, `Pillow`); keep the base
      install lean (rapidfuzz is already a core dep).
- [ ] T10 Unit test: `SampleUILAdapter` returns the fixture candidates, exposes a complete governance
      posture, and opens no socket (`tests/linkage/test_sample_uil.py`).

**Exit (Track B):** adapter loads the fixture, declares governance, no network reached.

---

## Track C — Linkage engine + LIA gate

- [ ] T11 Create `pipeline/linkage/blocking.py` — exact-Instagram-handle blocking; narrows the
      candidate set before scoring (LSH explicitly deferred to v3b).
- [ ] T12 Create `pipeline/linkage/features.py` — `AgreementVector` with 5 families: handle (exact +
      Jaro-Winkler via `rapidfuzz`), display_name (Jaro-Winkler), profile_photo (pHash Hamming,
      behind `[uil]`, weight 0 if `imagehash`/`Pillow` absent), website (exact host, `urllib.parse`),
      bio (Jaccard token-set). Each family emits a `feature_evidence` entry.
- [ ] T13 Create `pipeline/linkage/scoring.py` — Fellegi-Sunter log-LR with named constants
      `M_PRIORS`, `U_PRIORS`, `T_LINK`, `T_POSSIBLE`, `SURFACE_THRESHOLD = 0.7`;
      `confidence = logistic(LR)`; map LR → `link|possible_link|non_link`.
- [ ] T14 Create `pipeline/linkage/gate.py` — `surfaceable = (confidence ≥ 0.7) AND
      (human_review_status == "approved")`; `manual_review_required = confidence < 0.7`;
      `multi_match_flag` for platform groups with >1 link/possible_link; Art. 9-adjacent without
      `consent_record_id` never surfaceable; pHash never alone pushes to surfaceable.
- [ ] T15 Add `uil_lia_gate(handle, governance)` to `pipeline/compliance/tos.py` raising a typed
      `UilLiaError` (subclass of the existing `ComplianceError`) when `config.lia_file_path` is
      null/missing; export it via `pipeline/compliance/__init__.py`.
- [ ] T16 Unit tests (`tests/linkage/test_features.py`, `test_scoring.py`, `test_gate.py`): feature
      agreement monotonicity; LR → threshold mapping; gate truth table (confidence × review ×
      consent → surfaceable); pHash no-op without the extra; `uil_lia_gate` raises at entry.

**Exit (Track C):** engine + gate + LIA unit tests green.

---

## Track D — Stage 4 orchestrator + CLI wiring

- [ ] T17 Create `pipeline/stage4_linkage.py` — `run(handle, project_dir)`: `uil_lia_gate()` →
      adapter fetch → blocking → features → scoring → gate → `jsonschema` validate → atomic
      (`.tmp` + `os.replace`) write `04-linkage.json`. Reads only `02-normalized.json` + fixture.
- [ ] T18 Wire `STAGE_MAP[4] = stage4_linkage.run` in `profile_analyst.py`; leave the `--stage all`
      expansion (`1,2,3,6,7,8,9`) unchanged.
- [ ] T19 Unit test: `_parse_stages("all")` excludes 4; `_parse_stages("4")` resolves to the
      orchestrator (`tests/linkage/test_stage4_cli.py`).
- [ ] T20 Integration test: `--stage 4` over the committed fixture emits a schema-valid
      `04-linkage.json` with every candidate carrying confidence, likelihood_ratio, ≥1
      feature_evidence, and a classification.

**Exit (Track D):** `--stage 4` emits schema-valid linkage from the fixture; `all` excludes 4.

---

## Track E — Stage 6 surfacing

- [ ] T21 Edit `pipeline/stage6_dossier.py` — if `04-linkage.json` exists, fill the dossier
      `linkage` block with `surfaceable == true` candidates, re-running the gate (defense-in-depth);
      else keep `{"status": "deferred", "candidates": []}`.
- [ ] T22 Integration test: with an approved+surfaceable candidate, the dossier `linkage` block is
      populated; with none approved (or no artifact), it stays `{"status": "deferred"}`
      (`tests/linkage/test_stage6_surfacing.py`).

**Exit (Track E):** Stage 6 surfaces approved candidates only; placeholder preserved otherwise.

---

## Track F — Test suite, fixture end-to-end & validate

- [ ] T23 End-to-end test: `--stage 2` (or fixture) → `--stage 4` → `--stage 6` produces a dossier
      whose `linkage` block reflects the gate outcome; assert no network reached.
- [ ] T24 Verify A5 (Art. 9 consent gate) and A7 (pHash graceful degradation without `[uil]`) are
      covered by an explicit test each.
- [ ] T25 Run `make validate` — confirm green with `04-linkage.schema.json` registered and spec
      0011 `metadata.yml` (`status: accepted`) passing.
- [ ] T26 Run the offline unit suite (`pytest tests/linkage/` + the existing non-graph suite) —
      confirm green and that `SampleUILAdapter` opens no socket.

**Exit (Track F):** A1–A8 met; `make validate` green; `tests/linkage/` green offline.

**Total: ~26 tasks across 6 tracks.**

## Out of scope (do not include in this PR)

- Live cross-platform adapters (Twitter/X, TikTok, YouTube APIs) — separate future spec.
- v3b features: stylometry, network structure, temporal, PALE-style embedding.
- LSH blocking via `datasketch`.
- Stage 7 graph writeback of `SAME_AS` edges (D9 — deferred).
- Adding Stage 4 to `--stage all`.
