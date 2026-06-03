# Spec 0016 — Layer 3 Creator Diagnostics

Status: accepted · Date: 2026-06-03 · Method: Spec-Driven Development

---

## 0. Philosophy (SDD)

This spec describes **what** and **why**, separated from **how**. Each section defines:

1. **Intent** — purpose of the component.
2. **Inputs** — format and expected structure.
3. **Outputs** — format and structure produced.
4. **Invariants** — rules that may never be violated.
5. **Failure modes** — what counts as failure; what the component does NOT do.

The implementation lives in `pipeline/diagnostics.py`, `pipeline/models.py`,
`pipeline/stage6_dossier.py`, and `schemas/06-dossier.schema.json`.
This spec is the source of truth.

---

## 1. Problem

Stage 6 currently transforms raw features and scores directly into a report.
The report describes facts ("ER: 6.3%, follower tier: Mid") but stops short of interpretation.

A brand manager reading the report must still answer:
- *What kind of creator is this?*
- *Is this profile ready for a sponsorship?*
- *What categories of brands would fit?*
- *What risks exist?*

These questions require a layer of interpretation that sits between raw signals
and the final narrative — **Layer 3: Creator Diagnostics**.

The root cause of the gap: there is no stage that converts features + scores into
structured, queryable, versioned diagnostic labels. The narrative today is written
directly from numbers; labels are never persisted.

---

## 2. Goals / Non-Goals

### Goals

- Stage 6 produces two new top-level blocks in `06-dossier.json`:
  - `derived_insights` — content-level observations (theme_mix, top_topics, format_mix, editorial_consistency)
  - `derived_diagnostics` — interpretive labels (archetype, size, lifecycle, readiness, brand fit, risks)
- All diagnostic fields carry `method`, `version`, and (where applicable) `confidence` and `evidence`.
- Labels are stable keys; narratives are rendered at report time from those keys.
- `derived_diagnostics` fields are Neo4j-queryable: `c.creator_archetype = "specialist_educator"`, `"saas" IN c.brand_fit`.
- `report.md` renders a new **Creator Diagnostics** section with archetype, lifecycle, brand fit, risk, and readiness verdicts.
- All compute functions are pure — no I/O, no side effects, unit-testable in isolation.
- No new external Python dependencies.

### Non-Goals

| Out of scope | Reason | Target |
|---|---|---|
| LLM-based archetype classification | Rule-based v1 is sufficient for MVP; LLM adds cost without clear accuracy lift | future spec |
| Score recalculation from diagnostics | Diagnostics read scores, they do not produce them | future spec |
| Audience-demographics diagnostics | Requires creator consent per GDPR Art. 9; deferred | future spec |
| Backfill of existing dossier artifacts | Diagnostics are computed on each Stage 6 run; no migration needed | n/a |

---

## 3. Data Architecture

```
02-normalized.json (media[])
        │
        ▼
pipeline/diagnostics.py
        │
        ├─► build_derived_insights()
        │     └── ContentAnalysis
        │           ├── theme_mix          (heuristic — hashtag→theme lookup)
        │           ├── top_topics         (heuristic — captions+hashtags freq)
        │           ├── editorial_consistency_score  (heuristic — thematic concentration)
        │           └── content_format_mix (computed  — media_type distribution)
        │
        └─► build_derived_diagnostics()
              ├── creator_archetype      (rule_based)
              ├── creator_size           (computed)
              ├── lifecycle_stage        (rule_based)
              ├── sponsorship_readiness  (score_derived)
              ├── brand_fit[]            (rule_based)
              └── risk_flags[]           (rule_based + score_derived)

03-features.json + scores{}
        │
        └─► build_derived_diagnostics()   (same call, reads feats + scores)
```

**Key architectural constraint (D1):** `derived_insights` contains observations
derived from raw media data. `derived_diagnostics` contains interpretations derived
from features, scores, and insights. The two blocks are separate top-level objects
in `06-dossier.json`.

---

## 4. Inputs

### 4.1 `02-normalized.json` — `media[]`

Each media item used for content analysis:

```json
{
  "media_id": "m001",
  "media_type": "REEL",
  "hashtags": ["chatgpt", "openai", "aitools"],
  "caption": "Five AI tools I use every day..."
}
```

Fields consumed: `media_id` (stable identifier), `media_type`, `hashtags`, `caption`.

### 4.2 `03-features.json` — feature index

Features consumed by `build_derived_diagnostics`:

| Feature ID | Used for |
|---|---|
| `primary_niche` | archetype, lifecycle, brand_fit |
| `secondary_niches` | brand_fit (discounted) |
| `follower_tier` | creator_size, lifecycle_stage |
| `er_by_followers` | lifecycle_stage (ER override) |
| `posting_frequency_per_week` | archetype |
| `posting_consistency_score` | lifecycle_stage, sponsorship_readiness |
| `sponsored_posts` | archetype (commercial_ratio) |
| `likely_sponsored_undisclosed` | archetype (commercial_ratio) |
| `comment_pod_signal` | risk_flags |
| `engagement_anomaly` | risk_flags |
| `ftc_disclosure_status` | sponsorship_readiness, risk_flags |

### 4.3 Existing scores (`DossierScore` objects)

| Score | Used for |
|---|---|
| `authenticity.value` | sponsorship_readiness (40% weight) |
| `brand_safety.value` | sponsorship_readiness (30% weight), risk_flags |

---

## 5. Output

### 5.1 `derived_insights` block

```json
{
  "derived_insights": {
    "computed_at": "2026-06-03T10:00:00Z",
    "content_analysis": {
      "theme_mix": {
        "values": { "ai_tools": 0.75, "automation": 0.42 },
        "unmapped_ratio": 0.18,
        "confidence": 0.82,
        "method": "heuristic",
        "version": "v1"
      },
      "top_topics": [
        {
          "topic": "chatgpt",
          "share": 0.67,
          "evidence_media_ids": ["m001", "m004", "m009"]
        }
      ],
      "editorial_consistency_score": {
        "value": 78,
        "method": "heuristic"
      },
      "content_format_mix": {
        "values": { "reel": 0.58, "image": 0.25, "carousel_album": 0.17 },
        "method": "computed"
      }
    }
  }
}
```

### 5.2 `derived_diagnostics` block

```json
{
  "derived_diagnostics": {
    "computed_at": "2026-06-03T10:00:00Z",
    "creator_archetype": {
      "value": "specialist_educator",
      "confidence": 0.81,
      "method": "rule_based",
      "version": "v1",
      "evidence": ["niche_professional", "high_editorial_consistency"],
      "matched_rule": "specialist_educator_v1_r1"
    },
    "creator_size": {
      "value": "micro",
      "method": "computed"
    },
    "lifecycle_stage": {
      "value": "early_growth",
      "confidence": 0.75,
      "method": "rule_based",
      "version": "v1",
      "evidence": ["follower_tier_micro", "posting_consistency_high"],
      "matched_rule": "early_growth_v1_base"
    },
    "sponsorship_readiness": {
      "value": "medium",
      "confidence": 0.70,
      "method": "score_derived",
      "version": "v1",
      "evidence": ["auth_score_75", "brand_safety_85", "ftc_unknown"],
      "matched_rule": "medium_v1_r1"
    },
    "brand_fit": [
      { "category": "ai_tools",  "fit": "high",   "confidence": 0.86, "method": "rule_based" },
      { "category": "saas",      "fit": "high",   "confidence": 0.79, "method": "rule_based" },
      { "category": "education", "fit": "high",   "confidence": 0.70, "method": "rule_based" }
    ],
    "risk_flags": [
      {
        "flag": "unknown_commercial_history",
        "severity": "low",
        "method": "rule_based",
        "evidence": ["ftc_disclosure_unknown"]
      }
    ]
  }
}
```

### 5.3 `report.md` — new Creator Diagnostics section

Rendered after section 7 (Provenance). Labels → display strings via static maps; no LLM.

```markdown
---

## Creator Diagnostics

### Creator Archetype: Specialist Educator

Deep educational content in a defined niche. Audience seeks learning.

_Evidence: niche_professional, high_editorial_consistency · Rule: `specialist_educator_v1_r1` · Confidence: 81%_

---

### Lifecycle Stage: Early Growth

Audience forming. Niche defined. Consistency is the next lever.

_Creator size: micro · Confidence: 75%_

---

### Sponsorship Readiness: Medium

Partnership potential present. Some signals need strengthening.

---

### Brand Fit

**High fit:** Ai Tools, Saas, Education

---

### Risk Assessment

| Risk                        | Severity |
|-----------------------------|----------|
| Unknown Commercial History  | Low      |

> All diagnostics are derived labels, not facts. Recomputed each pipeline run.
```

### 5.4 Invariants

- **Labels only in JSON:** no `derived_diagnostics` field value is a prose string. Labels, numbers, enums, lists only.
- **No prose longer than 50 characters** in any `derived_diagnostics` JSON value.
- **Computed fields have no confidence:** fields with `method: computed` must not include a `confidence` key.
- **Heuristic/LLM fields require confidence:** fields with `method: heuristic` or `method: llm` must include `confidence`.
- **Pure functions:** all compute functions in `pipeline/diagnostics.py` are stateless and have no I/O.
- **Additive only:** no existing field in `06-dossier.json` or `report.md` is modified.
- **evidence_media_ids are stable:** topic evidence uses `media_id` string values, not positional indices.
- **FTC override:** `ftc_status = at_risk` overrides `sponsorship_readiness` to `low` regardless of score formula.

### 5.5 Failure modes

- `media[]` empty → `content_analysis.theme_mix = null`, `top_topics = []`, `content_format_mix = null`. Not an error.
- `primary_niche` not in brand fit lookup table → `brand_fit = []`. Not an error.
- All hashtags are noise → `theme_mix.values = {}`, `unmapped_ratio = 1.0`, `confidence = 0.0`.
- Feature missing from index → compute function receives `None` and falls back to neutral/default. Never crashes.

---

## 6. Computation Logic

### 6.1 Content Analysis

#### `content_format_mix` (computed — deterministic)

Count `media_type` occurrences across all media items. Normalize to proportions. Keys are lowercased.
No confidence field (fully deterministic).

#### `top_topics` (heuristic — v1)

```
tokens = lowercase_hashtags(filtered by noise blocklist, len ≥ 3)
       + caption_words(≥4 chars, filtered by stop words)

topic_posts[token] = set of media_ids where token appears
share[token]       = |topic_posts[token]| / total_posts

Return top 10 by share descending.
evidence_media_ids = sorted(topic_posts[token])[:5]
```

Noise blocklist (non-informative engagement bait): `fyp`, `viral`, `trending`, `explore`,
`reels`, `instagram`, `instagood`, `love`, `follow`, `like`, `share`, `foryou`, `foryoupage`,
`photooftheday`, `picoftheday`.

#### `theme_mix` (heuristic — v1)

Map hashtags to themes via static lookup table. Track unmapped count.

```
unmapped_ratio = unmapped_hashtags / total_non_noise_hashtags
confidence     = 1.0 - unmapped_ratio
theme_posts[theme] = set of media_ids with ≥1 hashtag mapping to that theme
values[theme]      = |theme_posts[theme]| / total_posts
```

**Hashtag → theme mapping (v1 lookup table):**

| Hashtag | Theme |
|---|---|
| ai, chatgpt, openai, llm, gpt, aiagents, artificialintelligence, machinelearning, deeplearning | ai_tools |
| automation | automation |
| tech, technology, programming, coding | tech_general |
| fitness, workout, gym, homeworkout, fitlife, exercise | fitness |
| health, healthy | health |
| wellness | wellness |
| nutrition, diet | nutrition |
| food, recipe, cooking, mealprep, healthyfood, healthyeating | food |
| lifestyle, motivation, mindset | lifestyle |
| travel, wanderlust, adventure | travel |
| fashion, style, ootd | fashion |
| beauty, makeup, skincare | beauty |
| finance, investing, crypto, money, personalfinance | finance |
| education, learning, study | education |

#### `editorial_consistency_score` (heuristic — v1)

```
max_concentration = max(theme_mix.values.values())
mapped_ratio      = 1.0 - theme_mix.unmapped_ratio
score             = int(round(max_concentration * mapped_ratio * 100))
```

Range: 0–100. A creator with 90% of posts in `ai_tools` and 0% unmapped → score 90.
The same creator but 50% unmapped → score 45.
This measures thematic coherence, **not** posting frequency. `posting_consistency_score`
remains a separate Stage 3 feature.

### 6.2 Creator Archetype (rule_based — v1)

Priority-ordered rules. First matching rule wins.

| Rule ID | Condition | Archetype |
|---|---|---|
| `specialist_educator_v1_r1` | `niche ∈ PROFESSIONAL_NICHES` AND `editorial_consistency ≥ 70` AND `commercial_ratio < 0.20` | specialist_educator |
| `thought_leader_v1_r1` | `niche ∈ PROFESSIONAL_NICHES` AND `freq < 2/week` AND `ER ≥ 1.2× benchmark` | thought_leader |
| `brand_builder_v1_r1` | `commercial_ratio ≥ 0.20` | brand_builder |
| `entertainer_v1_r1` | `niche ∈ ENTERTAINMENT_NICHES` AND `freq ≥ 5/week` | entertainer |
| `lifestyle_blogger_v1_r1` | `niche ∈ LIFESTYLE_NICHES` | lifestyle_blogger |
| `content_creator_v1_fallback` | (all else) | content_creator |

```
PROFESSIONAL_NICHES = {AI/Technology, Technology, Finance, Business, Education,
                       Science, Health, Medicine, Law, Marketing, Engineering}
ENTERTAINMENT_NICHES = {Entertainment, Gaming, Comedy, Music, Dance, Sports}
LIFESTYLE_NICHES = {Lifestyle, Fashion, Beauty, Travel, Food/Cooking,
                    Fitness/Health, Home/Garden, Parenting}
```

`confidence = niche_conf × rule_match_strength` (0.85–0.90 for specific rules, 0.50 for fallback).

`commercial_ratio = (sponsored_posts + likely_sponsored_undisclosed) / max(total_posts, 1)`.

### 6.3 Creator Size (computed — no confidence)

Direct mapping from `follower_tier`:

| follower_tier | creator_size |
|---|---|
| Nano | nano |
| Micro | micro |
| Mid | mid |
| Macro | macro |
| Mega | mega |

### 6.4 Lifecycle Stage (rule_based — v1)

Base from tier, then overrides:

```
base = {Nano→nascent, Micro→early_growth, Mid→scaling, Macro→established, Mega→mature}

Override 1: ER < 0.5× benchmark (any tier above Nano) → plateaued
Override 2: tier=Micro AND consistency < 0.3          → nascent (stalled)
```

`confidence` degrades with missing data: 0.80 with ER + consistency available, 0.70 with only tier.

### 6.5 Sponsorship Readiness (score_derived — v1)

```
Hard override: ftc_status = at_risk → value = low (confidence = 0.90)

raw = 0.40 × authenticity_score
    + 0.30 × brand_safety_score
    + 0.20 × (posting_consistency × 100)
    + 0.10 × ftc_score        # compliant=100, partial=60, unknown=50, at_risk=0

raw ≥ 65  → high
raw 40–64 → medium
raw < 40  → low
```

### 6.6 Brand Fit (rule_based — v1)

Static lookup table: `niche → list of (category, fit, base_confidence)`.
Confidence per entry = `base_confidence × primary_niche_conf`.
Secondary niches contribute at `× 0.60` discount.
One entry per category; highest confidence wins when primary and secondary overlap.
Sorted by confidence descending.

**Niche → brand categories (v1 lookup):**

| Niche | Category | Fit | Base Confidence |
|---|---|---|---|
| AI/Technology | ai_tools | high | 0.95 |
| AI/Technology | saas | high | 0.88 |
| AI/Technology | productivity_apps | high | 0.82 |
| AI/Technology | education | high | 0.78 |
| AI/Technology | tech_hardware | medium | 0.70 |
| Technology | saas | high | 0.88 |
| Technology | tech_hardware | high | 0.82 |
| Technology | ai_tools | high | 0.85 |
| Fitness/Health | activewear | high | 0.90 |
| Fitness/Health | supplements | high | 0.88 |
| Fitness/Health | health_apps | high | 0.80 |
| Fitness/Health | wellness | medium | 0.75 |
| Finance | fintech | high | 0.88 |
| Finance | investment_apps | high | 0.82 |
| Finance | insurance | medium | 0.65 |
| Education | online_courses | high | 0.90 |
| Education | edtech | high | 0.85 |
| Education | books | medium | 0.75 |
| Lifestyle | fmcg | high | 0.80 |
| Lifestyle | home_decor | high | 0.78 |
| Fashion | fashion_brands | high | 0.92 |
| Fashion | beauty | high | 0.85 |
| Beauty | beauty | high | 0.95 |
| Beauty | skincare | high | 0.92 |
| Food/Cooking | food_brands | high | 0.90 |
| Food/Cooking | kitchen_tools | high | 0.85 |
| Travel | travel_brands | high | 0.90 |
| Travel | hotels | high | 0.85 |
| Gaming | gaming_hardware | high | 0.92 |
| Entertainment | streaming_services | high | 0.85 |

### 6.7 Risk Flags (rule_based + score_derived — independent)

All flags are evaluated independently; multiple can fire simultaneously.

| Flag | Severity | Method | Trigger | Evidence token |
|---|---|---|---|---|
| small_audience | medium | rule_based | tier = Nano | follower_tier_nano |
| engagement_pod_detected | high | rule_based | comment_pod_signal = detected | comment_pod_signal_detected |
| ftc_risk | high | rule_based | ftc_status = at_risk | ftc_disclosure_at_risk |
| unknown_commercial_history | low | rule_based | ftc_status = unknown | ftc_disclosure_unknown |
| low_brand_safety | high | score_derived | brand_safety_score < 40 | brand_safety_score_{value} |
| low_authenticity | medium | score_derived | authenticity_score < 40 | authenticity_score_{value} |
| automation_signals | high | rule_based | engagement_anomaly = spike | engagement_anomaly_spike |
| low_posting_frequency | low | rule_based | freq < 1/week | posting_frequency_{value}_per_week |

---

## 7. Project Layout

```
pipeline/
├── diagnostics.py             (NEW — all compute functions and orchestrators)
└── models.py                  (modified — Layer 3 Pydantic models appended)
└── stage6_dossier.py          (modified — call orchestrators; render diagnostics section)

schemas/
└── 06-dossier.schema.json     (modified — derived_insights + derived_diagnostics optional blocks)

specs/0016-layer3-creator-diagnostics/
├── spec.md                    (this file)
├── metadata.yml
├── plan.md
├── tasks.md
└── summary.md
```

---

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| A1 | `06-dossier.json` contains `derived_insights.content_analysis` with `theme_mix`, `top_topics`, `editorial_consistency_score`, `content_format_mix` |
| A2 | `06-dossier.json` contains `derived_diagnostics` with `creator_archetype`, `creator_size`, `lifecycle_stage`, `sponsorship_readiness`, `brand_fit`, `risk_flags` |
| A3 | Every field in `derived_diagnostics` carries `method` and `version`; every `heuristic` or `llm` field carries `confidence` |
| A4 | `editorial_consistency_score` is derived from thematic concentration; a creator posting consistently across diverse themes scores low |
| A5 | `theme_mix.unmapped_ratio` is present (0.0–1.0); it reflects the fraction of non-noise hashtags not in the lookup table |
| A6 | `top_topics` entries carry `evidence_media_ids` with stable `media_id` strings, not positional indices |
| A7 | `creator_size` has no `confidence` field; `lifecycle_stage` has `confidence` and `evidence` |
| A8 | `sponsorship_readiness` with `ftc_status=at_risk` always returns `value=low` regardless of auth or brand_safety scores |
| A9 | `brand_fit` entries carry `category`, `fit` (high\|medium\|low), `confidence`, `method` |
| A10 | `risk_flags` entries carry `flag`, `severity` (high\|medium\|low), `method`, `evidence` |
| A11 | `report.md` contains Creator Archetype, Lifecycle Stage, Sponsorship Readiness, Brand Fit, Risk Assessment sections |
| A12 | No string values longer than 50 characters in `derived_diagnostics` JSON |
| A13 | `make validate` passes; schema accepts the new blocks and rejects unknown fields inside them |
| A14 | All functions in `pipeline/diagnostics.py` are pure — unit-testable without filesystem or network |
| A15 | `make test` green; no pre-existing test is broken by this spec |

---

## 9. Dependencies

- **Spec 0001** (Stage 3 features) — `primary_niche`, `follower_tier`, `er_by_followers` must be present.
  Graceful degradation when any individual feature is missing.
- **Spec 0015** (Stage 6 dossier) — `derived_insights` and `derived_diagnostics` are additive to existing
  Stage 6 output; spec 0015 behavior is unchanged.
- No new external Python dependencies.
