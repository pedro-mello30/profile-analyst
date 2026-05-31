# Spec 0011 — Cross-Platform Identity Linkage (Stage 4, v3a)

> Status: **draft** · Owner: pedro · Depends on: 0001 (Stage 4 design §6, dossier `linkage` block), 0002 (graph load — only for the deferred SAME_AS writeback)
>
> Spec 0001 §6 *designed* Stage 4 (UIL) and left it deferred; Stage 6 emits a
> `{"status": "deferred"}` linkage placeholder. This spec **implements the v3a profile-attribute
> slice**: given a confirmed Instagram `Profile`, score candidate accounts on other platforms that
> belong to the same real-world entity, write `04-linkage.json`, and surface approved candidates in
> the dossier — all from a **local fixture, with no live network and no cloud egress**.

## 1. Context & motivation

Linkage is the one stage spec 0001 flagged as *highest legal risk* (§ table, row "Stage 4"): it
asserts that two accounts on different platforms are the same person. That is why it was deferred and
why this spec keeps it deliberately narrow:

- **Single-profile, few-to-one** matching only — no population-scale linkage, no data writeback to
  non-GDPR-aligned storage (0001 §6 scope boundary).
- **Opt-in, never on the default path.** `--stage all` stays `1,2,3,6,7,8,9`; linkage runs only via
  an explicit `--stage 4`. The highest-risk stage cannot be triggered by a routine full run.
- **Local fixture source.** v3a ingests candidate accounts from a `SampleUILAdapter` reading
  `projects/<handle>/00-input/cross_platform.json`, mirroring how `SampleAdapter` seeds Stage 1.
  Live cross-platform adapters (Twitter/X, TikTok, YouTube APIs and their ToS) are a **separate
  future spec** — this one proves the matching + scoring + compliance machinery end-to-end offline.

The deliverable is the realization of 0001 §6 v3a, nothing more: 5 agreement features, a
Fellegi-Sunter classifier, the LIA / Art. 9 gates, the `04-linkage.schema.json` contract, and Stage 6
surfacing behind the existing defense-in-depth gate.

## 2. Goals / Non-goals

**Goals**
- `--stage 4` produces `04-linkage.json` validating against `schemas/04-linkage.schema.json`.
- Five v3a agreement families compute over a normalized `Profile` + a local candidate fixture.
- Fellegi-Sunter log-LR scoring → `confidence` ∈ [0,1] + raw `likelihood_ratio` + per-feature
  `feature_evidence[]` (≥1) on every candidate.
- LIA gate at Stage 4 entry; Art. 9-adjacent targets require `consent_record_id` to be surfaceable.
- Stage 6 replaces the deferred placeholder with **approved, surfaceable** candidates only —
  re-applying the gate (defense-in-depth).
- The whole path is offline and idempotent: Stage 4 reads `02-normalized.json` (+ fixture) and writes
  only `04-linkage.json`.

**Non-goals**
- Live cross-platform adapters / real network calls (separate spec; `SampleUILAdapter` only here).
- v3b features — stylometry, network structure, temporal, PALE-style embedding (§9 / Future Work).
- LSH blocking via `datasketch` (v3b; v3a uses exact-handle blocking).
- Stage 7 graph load of `SAME_AS` edges (deferred; 0011 stops at JSON + dossier surfacing).
- Improving recall against the open web — v3a precision is the priority; a missed link is preferred
  to a wrong assertion of identity.

## 3. Design (v3a)

**Source — `adapters/cross_platform/`.** `base.py` defines `CrossPlatformAdapter(SourceAdapter)`,
inheriting the full governance posture so a candidate source declares ToS/GDPR basis before its data
enters (Architecture Invariant: governance-before-data). `sample_uil.py` is `SampleUILAdapter`,
reading a local multi-platform fixture; it reaches no network and declares `tos_compliant=True`,
`data_category="public_profile"`, `requires_creator_consent=True`.

**Blocking — `pipeline/linkage/blocking.py`.** v3a blocks on the **exact Instagram handle** across
target platforms first (leverages the ~45% handle-reuse rate; 0001 §6). With the sample adapter the
candidate set is exactly what the fixture supplies; blocking narrows it to plausibly-matching handles
before scoring. LSH is deferred to v3b.

**Agreement features — `pipeline/linkage/features.py`.** Five families build an `AgreementVector` per
candidate; each contributes a `feature_evidence` entry `{feature, agreement, detail}`:

1. **handle** — exact match (strong) + Jaro-Winkler similarity (`rapidfuzz`).
2. **display_name** — Jaro-Winkler similarity (`rapidfuzz`).
3. **profile_photo** — perceptual hash (pHash) Hamming distance; **behind the `[uil]` extra**
   (`imagehash`+`Pillow`). Absent extra → family contributes **weight 0**, never an error.
4. **website** — exact host match (`urllib.parse`).
5. **bio** — Jaccard similarity on token sets (TF-IDF cosine via `scikit-learn` optional).

**Scoring — `pipeline/linkage/scoring.py`.** Fellegi-Sunter: per family accumulate `log(m_i/u_i)` on
agreement and `log((1-m_i)/(1-u_i))` on disagreement → composite log-LR. `m`/`u` priors are named
constants with literature-grounded defaults (single source of truth). `confidence = logistic(LR)`;
the raw uncalibrated `likelihood_ratio` is emitted alongside for reviewer transparency. Thresholds
`T_link` / `T_possible` map LR → `link` / `possible_link` / `non_link`. `SURFACE_THRESHOLD = 0.7` is a
named constant.

**Gate — `pipeline/linkage/gate.py`.** `surfaceable = (confidence ≥ 0.7) AND
(human_review_status == "approved")`; `manual_review_required = confidence < 0.7`;
`multi_match_flag = true` on every candidate in a platform group with >1 link/possible_link (soft
constraint — never silently drop). Art. 9-adjacent targets without `consent_record_id` are never
surfaceable regardless of confidence. pHash is biometric-adjacent and only ever feeds confidence; it
can never *alone* push a candidate to surfaceable.

**Orchestrator — `pipeline/stage4_linkage.py`.** Thin `run(handle, project_dir)`:
`uil_lia_gate()` → adapter fetch → blocking → features → scoring → gate → schema-validate → atomic
write `04-linkage.json`. Idempotent; touches no other artifact.

**CLI wiring — `profile_analyst.py`.** `STAGE_MAP` gains `4 → stage4_linkage.run`. `--stage all`
expansion is **unchanged** (`1,2,3,6,7,8,9`); Stage 4 is reachable only by explicit `--stage 4`.

**Stage 6 surfacing — `pipeline/stage6_dossier.py`.** If `04-linkage.json` exists, Stage 6 fills the
dossier `linkage` block with the candidates whose `surfaceable == true`, re-running the gate
(defense-in-depth); if none qualify, or the artifact is absent, it keeps the existing
`{"status": "deferred", "candidates": []}` placeholder.

## 4. Decisions

See `metadata.yml` `decisions:` for the authoritative list (D1–D9): opt-in wiring (D1), local
`SampleUILAdapter` source (D2), the five v3a families with pHash behind `[uil]` (D3), Fellegi-Sunter
scoring + named priors/thresholds (D4), exact-handle blocking (D5), the `04-linkage.schema.json`
contract (D6), the LIA / Art. 9 / surfaceable gates (D7), Stage 6 surfacing semantics (D8), and the
deferral of the `SAME_AS` graph writeback (D9).

## 5. Compliance

Linkage carries the project's heaviest GDPR load and the gates are not optional:

- **LIA gate (Art. 6(1)(f)).** `compliance.tos.uil_lia_gate(handle, governance)` **raises** at Stage 4
  entry when `config.lia_file_path` is null or the file is missing — the Legitimate-Interests
  Assessment must exist before any cross-platform candidate is scored.
- **Art. 9.** Linking accounts can reveal special-category data (e.g. an LGBTQ+ or religious community
  account). Art. 9-adjacent candidates require an explicit `consent_record_id`; without it they are
  never surfaceable. The Art. 9 scanner's defense-in-depth posture (0001) extends to the linkage
  evidence text.
- **Art. 22.** A surfaced link is a decision affecting a person, so every candidate carries
  `feature_evidence[]` (≥1) — the same explainability bar as a dossier score — plus a human-review
  path (`human_review_status`) and the `manual_review_required` flag.
- **Surfaceable rule** is enforced twice — at Stage 4 emission and Stage 6 assembly — so a contributor
  who bypasses Stage 4's gate cannot leak an unapproved link through Stage 6.

## 6. Acceptance

Authoritative list in `metadata.yml` `acceptance:` (A1–A8, all `status: planned`): opt-in stage
wiring (A1), LIA gate raises at entry (A2), schema-valid emission with full evidence (A3),
review/threshold flags (A4), Art. 9 consent gate (A5), Stage 6 surfacing semantics (A6), pHash graceful
degradation without the `[uil]` extra (A7), and `make validate` + offline unit suite green with the
adapter reaching no network (A8).

## 7. Module layout / components

```
adapters/cross_platform/
├── base.py                 # CrossPlatformAdapter(SourceAdapter) — inherits governance
└── sample_uil.py           # SampleUILAdapter — local multi-platform fixture, no network
pipeline/
├── stage4_linkage.py       # thin idempotent orchestrator → 04-linkage.json
└── linkage/
    ├── blocking.py         # exact-handle blocking (v3a); LSH deferred to v3b
    ├── features.py         # 5-family AgreementVector + feature_evidence
    ├── scoring.py          # Fellegi-Sunter log-LR + named m/u priors + thresholds
    └── gate.py             # SURFACE_THRESHOLD + human-review + Art.9 consent gate
schemas/04-linkage.schema.json   # draft-7; method_version enum "v3a"
projects/<handle>/00-input/cross_platform.json   # SampleUILAdapter fixture
```
Plus edits to `profile_analyst.py` (`STAGE_MAP`), `pipeline/stage6_dossier.py` (surfacing),
`pipeline/models.py` (`LinkageDocument`, `LinkageCandidate`), `pyproject.toml` (`[uil]` extra:
`imagehash`, `Pillow`), and `pipeline/compliance/tos.py` (`uil_lia_gate`).

## 8. Test plan

- **Offline unit suite (`tests/linkage/`).** Feature families against synthetic pairs (exact/near/no
  match); Fellegi-Sunter LR monotonicity and threshold mapping; gate truth table
  (confidence × review × consent → surfaceable); pHash family no-ops when the `[uil]` extra is absent.
- **Stage integration.** `SampleUILAdapter` over a committed fixture → schema-valid `04-linkage.json`;
  `_parse_stages` proves `all` excludes 4 and `--stage 4` includes it.
- **Stage 6.** Approved+surfaceable candidate replaces the placeholder; none-approved keeps
  `{"status":"deferred"}`. The unit suite stays offline (Architecture Invariant) — no network.

## 9. Future work (v3b and beyond)

- **v3b features:** stylometry (capped weight, never a sole `link` trigger), network structure
  (weight 0 without graph data), temporal posting histograms, PALE-style supervised embedding.
- **LSH blocking** via `datasketch` once the candidate corpus grows.
- **Stage 7 writeback:** persist surfaced links as `SAME_AS` edges in Neo4j (separate spec; D9).
- **Live cross-platform adapters** (Twitter/X, TikTok, YouTube) with their own governance posture and
  ToS review — the spec that turns v3a from fixture-fed into real discovery.
- **Prior calibration:** estimate `m`/`u` from a labeled anchor set instead of literature defaults.
