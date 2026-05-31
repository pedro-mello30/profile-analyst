# Plan 0011 — Cross-Platform Identity Linkage (Stage 4, v3a)

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
Realizes the deferred Stage 4 (UIL v3a) designed in spec 0001 §6, the same way spec 0010 realized
0003's Ollama backend. Net-new code is confined to `adapters/cross_platform/`, `pipeline/linkage/`,
`pipeline/stage4_linkage.py`, one new schema, and small edits to `models.py`, `stage6_dossier.py`,
`compliance/tos.py`, `profile_analyst.py`, and `pyproject.toml`. **No live network, no cloud egress.**

## Architecture (reference)

```
02-normalized.json ──┐
                     │   uil_lia_gate()  (raises if LIA absent)
SampleUILAdapter ────┤        │
(00-input/           ▼        ▼
 cross_platform.json)  pipeline/stage4_linkage.run(handle, project_dir)
                              │
              ┌───────────────┼───────────────┬────────────────┐
              ▼               ▼               ▼                ▼
        blocking.py      features.py      scoring.py        gate.py
      (exact-handle)   (5 families →    (Fellegi-Sunter   (SURFACE_THRESHOLD=0.7,
                        AgreementVector)  log-LR →          human-review,
                                          confidence)       Art.9 consent)
              └───────────────┴───────────────┴────────────────┘
                              │  schema-validate (04-linkage.schema.json)
                              ▼  atomic write
                      projects/<handle>/04-linkage.json
                              │
                              ▼  (re-apply surfaceable gate)
                  stage6_dossier.run → dossier.linkage block
```

**Invariant:** Stage 4 reads only `02-normalized.json` + the fixture and writes only
`04-linkage.json` (idempotent). The `surfaceable` rule is enforced twice — at emission and at Stage 6
assembly — so neither gate alone is load-bearing. Stage 4 is opt-in: `--stage all` never runs it.

## Implementation tracks (dependency-ordered)

### Track A — Contract & models (foundation)

Define the inter-stage contract before any producer exists. Add
`schemas/04-linkage.schema.json` (draft-7) and register it in `tools/validate.py`. Add
`LinkageDocument` / `LinkageCandidate` Pydantic v2 types to `pipeline/models.py`.

Schema shape (per D6): top-level `method_version` enum `["v3a"]`, preserved `governance` block, and
`candidates[]` where each candidate has `platform`, `candidate_handle`, `confidence` (0–1),
`likelihood_ratio` (number), `feature_evidence[]` (`minItems: 1`, each `{feature, agreement, detail}`),
`classification` (`link|possible_link|non_link`), `multi_match_flag` (bool),
`manual_review_required` (bool), `human_review_status` (`pending|approved|rejected`),
`consent_record_id` (string|null), `surfaceable` (bool).

**Exit:** `make validate` is green with the new schema registered; `LinkageDocument` round-trips a
hand-written sample candidate and rejects one missing `feature_evidence`.

### Track B — Cross-platform source + `[uil]` extra (parallel with A)

Add the ingestion boundary for candidate accounts. `adapters/cross_platform/base.py` defines
`CrossPlatformAdapter(SourceAdapter)` carrying the full governance posture (inherited ABC).
`adapters/cross_platform/sample_uil.py` is `SampleUILAdapter`, reading
`projects/<handle>/00-input/cross_platform.json` — no network. Declare `tos_compliant=True`,
`data_category="public_profile"`, `requires_creator_consent=True`. Add the optional `[uil]` extra
(`imagehash`, `Pillow`) to `pyproject.toml` and commit a sample fixture for one handle.

**Exit:** `SampleUILAdapter("<handle>").fetch_*` returns the fixture's candidate accounts, declares a
complete governance posture, and a unit test confirms it opens no socket.

### Track C — Linkage engine + LIA gate (depends on A)

The core matching logic under `pipeline/linkage/`:
- `blocking.py` — exact-Instagram-handle blocking (v3a); narrows the candidate set.
- `features.py` — 5-family `AgreementVector` (handle exact + Jaro-Winkler via `rapidfuzz`;
  display_name Jaro-Winkler; profile_photo pHash Hamming **behind `[uil]`**, weight 0 if absent;
  website exact host via `urllib.parse`; bio Jaccard token-set). Each family emits a
  `feature_evidence` entry.
- `scoring.py` — Fellegi-Sunter: per-family `log(m/u)` / `log((1-m)/(1-u))` → composite log-LR;
  `confidence = logistic(LR)`; named constants `M_PRIORS`, `U_PRIORS`, `T_LINK`, `T_POSSIBLE`,
  `SURFACE_THRESHOLD = 0.7`.
- `gate.py` — `surfaceable = (confidence ≥ 0.7) AND (human_review_status == "approved")`;
  `manual_review_required = confidence < 0.7`; `multi_match_flag` on platform groups with >1
  link/possible_link; Art. 9-adjacent without `consent_record_id` is never surfaceable; pHash never
  alone pushes to surfaceable.
- `compliance/tos.py` — add `uil_lia_gate(handle, governance)` raising a typed `UilLiaError`
  (`ComplianceError` subclass) when `config.lia_file_path` is null/missing.

**Exit:** unit tests green for feature monotonicity, LR→threshold mapping, the gate truth table
(confidence × review × consent), pHash no-op without the extra, and `uil_lia_gate` raising at entry.

### Track D — Stage 4 orchestrator + CLI wiring (depends on A, B, C)

`pipeline/stage4_linkage.py`: thin idempotent `run(handle, project_dir)` —
`uil_lia_gate()` → adapter fetch → blocking → features → scoring → gate → schema-validate →
atomic write `04-linkage.json`. Wire `STAGE_MAP[4] = stage4_linkage.run` in `profile_analyst.py`,
leaving the `--stage all` expansion (`1,2,3,6,7,8,9`) **unchanged**.

**Exit:** `--stage 4` over the committed fixture emits a schema-valid `04-linkage.json`;
`_parse_stages("all")` excludes 4; `--stage 4` resolves to the orchestrator (unit-tested).

### Track E — Stage 6 surfacing (depends on A, D)

`pipeline/stage6_dossier.py`: if `04-linkage.json` exists, fill the dossier `linkage` block with
`surfaceable == true` candidates, re-running the gate; otherwise keep the existing
`{"status": "deferred", "candidates": []}` placeholder.

**Exit:** with an approved+surfaceable candidate present, the dossier `linkage` block is populated;
with none approved (or no artifact), it stays `{"status": "deferred"}`.

### Track F — Test suite, fixture end-to-end & validate (depends on A–E)

Consolidate `tests/linkage/` (unit + stage integration), add the fixture-backed end-to-end check
(`--stage 4` → `04-linkage.json` → Stage 6 surfacing), and confirm `make validate` plus the offline
unit suite are green with no network reached.

**Exit:** all acceptance criteria A1–A8 demonstrably met; `make validate` green; `tests/linkage/`
green offline.

**Dependency graph:** A → C → D; B → D; D → E; {A,B,C,D,E} → F. A and B run in parallel.

## Risks

- **Fellegi-Sunter priors are guesses without labeled data.** Hand-set `m`/`u` from literature can
  mis-rank candidates. *Mitigation:* named constants in one place; surfaceable still requires human
  approval, so a mis-rank cannot auto-surface a wrong link. Calibration is Future Work (OQ1).
- **pHash is biometric-adjacent.** Comparing profile photos edges toward Art. 9. *Mitigation:* pHash
  feeds confidence only, never alone pushes to surfaceable, lives behind the `[uil]` extra, and is
  covered by the same consent gate.
- **Over-surfacing a wrong identity link.** A false "same person" assertion is the worst failure here.
  *Mitigation:* double gate (Stage 4 + Stage 6), `manual_review_required`, LIA-at-entry, and v3a
  tuned for precision over recall.
- **`multi_match` ambiguity.** >1 plausible match in a platform group. *Mitigation:* soft
  `multi_match_flag` on all, never silently drop (0001 §6); surfacing still needs per-candidate
  approval.

## Open implementation questions

- **OQ1 — priors.** Ship literature-grounded `m`/`u` constants, or estimate from a labeled anchor
  set? *Default:* literature constants for v3a; calibration deferred.
- **OQ2 — multi_match surfacing.** Surface all flagged, or suppress the whole group pending review?
  *Default:* soft-flag all, never drop; reviewer decides per candidate.
- **OQ3 — live adapters.** Where do Twitter/X, TikTok, YouTube adapters + their ToS get specified?
  *Default:* a dedicated future adapter spec; out of scope here.
