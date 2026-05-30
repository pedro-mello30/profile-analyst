# Spec 0001 — Social-Media Associations Profile: Instagram-Seeded Unified Creator Dossier

Status: draft · Date: 2026-05-29 · Method: Spec-Driven Development

---

## 0. Philosophy (SDD)

This spec describes **what** and **why**, separated from **how** (implementation). Each stage section defines:

1. **Intent** — purpose of the stage.
2. **Inputs** — format and expected structure.
3. **Outputs** — format and structure produced.
4. **Invariants** — rules that may never be violated.
5. **Failure modes** — what counts as failure; what the stage does NOT do.

The implementation lives in `pipeline/`; the spec is the source of truth. No code change is valid
without a corresponding spec section that justifies it.

---

## 1. Problem

Influencer marketing decisions — selecting creators, estimating reach, detecting fraud, scoring
brand fit — currently require either expensive third-party SaaS tools (HypeAuditor, Modash,
CreatorIQ) or manual research that does not scale. These tools are black boxes: they emit scores
without explaining which signals drove them, making them legally problematic under GDPR Art. 22
(automated decision-making) and practically opaque to brand teams.

At the same time, the data-access landscape has shifted sharply:

- **Instagram Basic Display API** was shut down 2024-12-04 — personal accounts have no supported
  API path.
- **Instagram Graph API** exposes only owned Business/Creator accounts and limited
  `business_discovery` lookups for public Business/Creator profiles. No follower lists, no
  third-party audience demographics.
- **Consent-based providers** (Phyllo, InsightIQ) offer first-party data but require creator
  enrollment and add cost.
- **Data brokers / scrapers** (Apify, Bright Data) operate in a gray zone — *Meta v. Bright Data*
  (2024) confirmed that logged-off scraping of public data does not breach Meta's ToS, but
  authenticated scraping and downstream profiling of real people carries real legal risk under
  GDPR and CCPA.

The result: there is no open-source, compliance-first, source-agnostic pipeline that produces a
structured, explainable creator dossier from Instagram profile data.

---

## 2. Goals / Non-Goals

### Goals

- A **staged, idempotent Python pipeline** that ingests an Instagram profile and produces a
  unified "associations profile dossier": niche, engagement quality, brand affinity, sponsored-post
  detection, audience authenticity signals, and (in later versions) cross-platform identity linkage
  and audience-overlap graph.
- A **source-agnostic ingestion layer** (`SourceAdapter` ABC) that abstracts data-governance
  metadata (data category, ToS compliance, GDPR basis, jurisdiction, retention policy) across all
  data sources. v1 ships `SampleAdapter` (reads local JSON fixture); live sources are deferred.
- **Explainable scores**: every computed metric emits its contributing signals. No black-box output.
- **Compliance first-class**: GDPR Art. 22 human-review path, Art. 9 special-category data
  flagging, FTC disclosure detection, per-source ToS-flag gate.
- A complete **SDD spec** that is the source of truth for all pipeline behavior and serves as the
  basis for hybrid multi-model ensemble refinement.

### Non-Goals (YAGNI — sequenced to later versions)

| Out of scope in v1 | Reason | Target |
|---|---|---|
| Stage 4 — Cross-platform identity linkage | Needs multi-profile network data; highest legal risk | v3 |
| Stage 5 — Association graph (overlap/community) | Needs multi-profile data; graph engine infrastructure | v2 |
| Live Instagram data fetching (Graph API adapter) | API restrictions; compliance posture not yet established | v2 |
| Audience demographics (age/gender/location breakdown) | Requires creator OAuth; not available for third-party profiles | v2 |
| Deep fake-follower sampling (follower-list traversal) | No follower list access via official API | v2 |
| Brand-to-creator matchmaking (AI compatibility scoring) | Requires brand profile input + multi-profile comparison | v2 |
| Audience overlap matrix across multiple creators | Multi-profile operation | v2 |
| Publishing pipeline (Buffer/Later/Hootsuite integration) | Out of scope |  — |
| Real-time API serving / dashboard UI | Out of scope | — |

---

## 3. Source-Agnostic Ingestion & Governance

### Intent

Decouple the pipeline from any specific data source. Every source must declare its data-governance
posture before any data enters the pipeline. The ToS-flag gate enforces this at runtime.

### SourceAdapter ABC

```python
class SourceAdapter(ABC):
    # Identity
    source_id: str          # "sample" | "instagram_graph_api" | "apify" | "phyllo" | ...
    data_category: str      # "OFFICIAL_API" | "CONSENT_BASED" | "PUBLIC_SCRAPE" | "DATA_BROKER" | "SAMPLE"
    tos_compliant: bool     # Is this source within the platform's ToS?

    # Authentication
    auth_type: str          # "NONE" | "OAUTH_USER" | "API_KEY" | "WEBHOOK"
    requires_creator_consent: bool

    # Rate limits
    calls_per_window: int
    window_seconds: int

    # Field availability
    available_fields: set[str]
    estimated_fields: set[str]   # modeled/inferred, not first-party

    # Legal
    gdpr_basis: str         # "CONSENT" | "LEGITIMATE_INTERESTS" | "CONTRACT" | "NONE"
    requires_lia: bool      # Legitimate Interests Assessment required?

    # Retention
    max_retention_days: int
    deletion_on_request: bool

    @abstractmethod
    def fetch_profile(self, handle: str) -> dict: ...

    @abstractmethod
    def fetch_media(self, profile_id: str, limit: int = 20) -> list[dict]: ...
```

### ToS-Flag Gate

At Stage 1 entry, the pipeline checks `adapter.tos_compliant`. If `False`, it raises
`TosComplianceError` unless the environment variable `ALLOW_NONCOMPLIANT=true` is explicitly set.
This variable is for test fixtures only — never for production data.

### Governance metadata on every raw record

Every record emitted by Stage 1 carries a `_governance` block:

```json
{
  "_governance": {
    "source_id": "sample",
    "data_category": "SAMPLE",
    "tos_compliant_at_ingest": true,
    "ingested_at": "2026-05-29T14:30:00Z",
    "gdpr_basis": "LEGITIMATE_INTERESTS",
    "subject_jurisdiction": "BR",
    "retention_expires_at": "2026-08-27T14:30:00Z",
    "consent_record_id": null
  }
}
```

`subject_jurisdiction` is inferred from profile location fields where available; defaults to
`"UNKNOWN"` when not determinable.

`retention_expires_at` is computed as `ingested_at + max_retention_days` from the adapter.

---

## 4. Canonical Entity Model

### Intent

Produce a single, consistent Python data model (`Profile`) that every downstream stage reads.
This is Stage 2's output — the canonical truth for a creator.

### Profile model (Pydantic)

```python
class Profile(BaseModel):
    # Identity
    handle: str
    platform: str = "instagram"
    profile_id: str | None = None
    display_name: str | None = None
    bio: str | None = None
    website: str | None = None
    is_verified: bool = False
    is_business: bool = False
    account_type: str | None = None   # "PERSONAL" | "BUSINESS" | "CREATOR"

    # Metrics (as-of snapshot)
    followers: int
    following: int
    post_count: int
    snapshot_at: str   # ISO datetime UTC

    # Media (recent posts, from most-recent to oldest)
    media: list[MediaItem]

    # Audience (only available with creator consent)
    audience: AudienceSummary | None = None

    # Governance (preserved from Stage 1)
    governance: GovernanceBlock
```

```python
class MediaItem(BaseModel):
    media_id: str
    media_type: str       # "IMAGE" | "VIDEO" | "CAROUSEL_ALBUM" | "REEL" | "STORY"
    posted_at: str        # ISO datetime UTC
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    views: int | None = None
    caption: str | None = None
    hashtags: list[str] = []
    mentions: list[str] = []
    is_paid_partnership: bool = False
    paid_partner_handle: str | None = None
```

### Invariants

- `followers`, `following`, `post_count` must be non-negative integers.
- `snapshot_at` must be ISO 8601 UTC.
- `media` is ordered most-recent first; empty list is valid (adapter may not provide media).
- `governance` is always present and fully populated.
- The canonical model is validated against `02-normalized.schema.json` before Stage 3 runs.

---

## 5. Feature Catalog

### Intent

Compute every metric that is derivable from a **single public Instagram profile** without
creator consent or multi-profile network access. Outputs a structured, schema-validated feature
document with per-feature `confidence` and `method`.

### Feature output structure

Every feature entry follows:

```json
{
  "feature_id": "er_by_followers",
  "value": 2.34,
  "unit": "percent",
  "confidence": 1.0,
  "method": "computed",
  "art9_risk": false,
  "signals": ["likes", "comments", "saves", "shares", "followers"],
  "notes": null
}
```

`method` values: `computed` (deterministic formula from raw data), `inferred` (heuristic
estimate), `llm` (Claude API output).

`art9_risk: true` is emitted for any feature whose value may correlate with health, sexual
orientation, religion, or political views (GDPR Art. 9 special categories).

### §5.1 Engagement Features (computable from public post data)

| Feature ID | Formula | Requires |
|---|---|---|
| `er_by_followers` | `sum(likes+comments+saves+shares) / n_posts / followers × 100` | posts + followers |
| `er_by_views` | `sum(likes+comments+shares) / sum(views) × 100` | video posts only |
| `comments_per_post_avg` | `mean(comments per post)` over last N posts | posts |
| `save_rate` | `mean(saves / reach)` — `null` if reach unavailable | reach (often absent) |
| `share_rate` | `mean(shares / reach)` | reach |
| `follower_tier` | Nano/Micro/Mid/Macro/Mega/Celebrity based on `followers` | followers |
| `follower_following_ratio` | `followers / max(following, 1)` | followers, following |

**Benchmark thresholds for `er_by_followers`:** Nano 8–15%, Micro 0.8–8%, Mid 0.73%, Macro 1.02%,
Mega 1.10%, Celebrity 1.20% (ClickAnalytic December 2025 data).

### §5.2 Growth & Posting Behavior

| Feature ID | Formula | Requires |
|---|---|---|
| `posting_frequency_per_week` | `post_count / days_span × 7` over available media window | posts with timestamps |
| `posting_consistency_score` | `1 - (std(intervals) / mean(intervals))` — range [0,1] | post timestamps |
| `avg_post_interval_hours` | `mean(time between consecutive posts)` | post timestamps |
| `estimated_reach_per_post` | `followers × (er_by_followers / 100)` [inferred] | followers, er |

Growth features (`follower_growth_rate`, `growth_velocity`, `spike_detection`) require
historical snapshots — emitted as `null` with `method: deferred` when unavailable.

### §5.3 Content Classification (Claude NLP)

Primary niche and secondary niche are inferred by Claude from captions and hashtags. The system
prompt instructs Claude to use the standard influencer taxonomy (Lifestyle, Beauty/Makeup, Fashion,
Fitness/Health, Food/Cooking, Travel, Tech/Gaming, Finance, Parenting, Pets, Sustainability,
Sports, Entertainment, Education, Business/Entrepreneurship, Other).

| Feature ID | Value type | Method |
|---|---|---|
| `primary_niche` | category string | `llm` |
| `secondary_niches` | list[str] | `llm` |
| `hashtag_fingerprint` | top-N characteristic hashtags | `computed` |
| `content_language` | ISO 639-1 code | `computed` (langdetect) |
| `caption_sentiment` | `positive` / `neutral` / `negative` | `llm` (art9_risk depends on niche) |

**Image features are the dominant signal on Instagram** (90.75% accuracy vs 60.9% text-only,
WWW 2020) but are deferred to v1.1 when a vision step is added. v1 uses text-only NLP.

### §5.4 Brand & Affinity (rule-based; NLP supplement)

| Feature ID | Value type | Method |
|---|---|---|
| `brand_mentions` | list of `{brand, count, context}` | `computed` (NLP @mention + #hashtag) |
| `brand_affinity_signals` | list of `{brand, category, confidence}` | `llm` |
| `influencer_category` | coarse category (Fashion, Fitness, …) | `llm` |

### §5.5 Sponsored Content Detection

Two-pass detection:

**Pass 1 — Rule-based (explicit signals):**
- Instagram "Paid Partnership with [Brand]" tag → `is_paid_partnership: true` on `MediaItem`
- Caption/hashtag patterns: `#ad`, `#sponsored`, `#gifted`, `#collab`, `#partner`,
  `#[brand]partner`, "Thanks to [brand]", "Sponsored by", "In collaboration with"

**Pass 2 — LLM classifier (implicit / undisclosed):**
- For posts where Pass 1 found no explicit signal, Claude classifies as `commercial` /
  `non-commercial` with confidence. Posts with `commercial` + no explicit disclosure flag are
  emitted as `undisclosed_sponsored: true`.

LLM-based sponsored detection achieves F1 ≈ 0.93 (InstaSynth, ICWSM 2024).

| Feature ID | Value type | Method |
|---|---|---|
| `sponsored_posts` | list[MediaItem.media_id] | `computed` (Pass 1) |
| `likely_sponsored_undisclosed` | list[MediaItem.media_id] | `llm` (Pass 2) |
| `ftc_disclosure_status` | `compliant` / `partial` / `at_risk` / `unknown` | `computed` |
| `sponsorship_history` | list of `{brand, first_seen, count, disclosure_type}` | `computed` |

**FTC compliance scoring:**
- `compliant` — all detected commercial posts have clear disclosure in caption or partnership tag.
- `partial` — ≥50% of detected commercial posts have disclosure.
- `at_risk` — <50% disclosure OR undisclosed commercial posts detected.
- `unknown` — insufficient data (<3 posts).

### §5.6 Authenticity Heuristics (single-profile, no follower-list access)

Deep fake-follower detection (Botometer-style, Cresci digital-DNA) requires traversal of the
follower list, which is not available via the official API for third-party profiles. v1 ships
single-profile heuristics only:

| Feature ID | Value | Basis |
|---|---|---|
| `follower_following_ratio` | float | Low ratio (< 0.1) is a fraud signal |
| `account_completeness_score` | 0–1 | Bio present, photo present, website present |
| `comment_pod_signal` | `detected` / `not_detected` / `unknown` | Recurring subset of commenters on ≥5 consecutive posts |
| `engagement_anomaly` | `none` / `low_engagement` / `spike` | ER far below tier benchmark OR sudden follower spike |

Full fake-follower analysis (Varol et al. 2017; Cresci et al. 2017 digital-DNA; Instagram-specific
ML F1=0.89) is deferred to v2 when multi-profile data is available.

---

## 6. Cross-Platform Identity Linkage (UIL) — Deferred to v3

### Intent

Given a confirmed Instagram profile, discover and score candidate accounts on other platforms
(Twitter/X, TikTok, YouTube, LinkedIn, etc.) that belong to the same real-world entity.

### Callable API (when implemented)

```python
# pipeline/stage4_linkage.py  →  pipeline/linkage/  (subpackage for testability)
class UILinker:
    def link_cross_platform(self, profile: Profile) -> LinkageDocument: ...
```

**Initial target platforms (v3a):** Twitter/X, TikTok, YouTube. LinkedIn and others in v3b+.

**Scope boundary:** Single-profile, few-to-one matching only. No population-scale linkage.
No data writeback to non-GDPR-aligned storage.

### Method design (for future implementation)

**v3a — Profile-attribute heuristics** (5 features; Shu et al. 2017; Zafarani & Liu 2013):

1. **Username / handle** — exact match (precision ~92%), Jaro-Winkler similarity (`rapidfuzz`).
   Practical blocking for v3a: search target platforms for the exact Instagram handle first
   (leverages ~45% handle-reuse rate); defer LSH to v3b when corpus grows.
2. **Display name** — Jaro-Winkler similarity (`rapidfuzz`).
3. **Profile photo** — perceptual hash (pHash, Hamming distance; `imagehash` optional extra).
4. **Website URL** — exact host match (`urllib.parse`).
5. **Bio text** — Jaccard similarity on token sets (or TF-IDF cosine via `scikit-learn`).

**v3b — Extended features (deferred):**

6. **Stylometry** — n-gram / function-word distribution (Vosoughi et al. 2015: 31% top-1
   on 5,612 users). Weak alone; never a sole `link` trigger; capped weight.
7. **Network structure** — degree/betweenness comparison across platform graphs (Narayanan &
   Shmatikov 2009). Optional; weight = 0 when no graph data available.
8. **Behavioral / temporal** — posting time-of-day histogram Pearson correlation (numpy).
9. **Supervised embedding** — PALE-style (IJCAI 2016) with anchor pairs from bio cross-links.

**Scoring** — Fellegi-Sunter: per feature accumulate `log(m_i/u_i)` for agreement,
`log((1-m_i)/(1-u_i))` for disagreement → composite log-LR → `T_link`/`T_possible`
thresholds → Link / Possible-link / Non-link. `confidence` = logistic(LR) → [0,1].
`likelihood_ratio` (raw, uncalibrated) emitted alongside `confidence` for reviewer transparency.
`SURFACE_THRESHOLD = 0.7` is a named constant (single source of truth).

**Module layout:**

```
pipeline/
├── stage4_linkage.py          # thin orchestrator (idempotent; emits 04-linkage.json)
└── linkage/
    ├── blocking.py             # handle-prefix blocking (v3a) → LSH via datasketch (v3b+)
    ├── features.py             # 5-family AgreementVector
    ├── scoring.py              # Fellegi-Sunter LR classifier
    ├── embedding.py            # v3b: PALE-style (pluggable, off by default)
    └── gate.py                 # SURFACE_THRESHOLD + human-review + Art.9 consent gate
adapters/cross_platform/
    ├── base.py                 # CrossPlatformAdapter ABC (inherits SourceAdapter governance)
    └── sample_uil.py           # SampleUILAdapter: reads local multi-platform fixture
schemas/04-linkage.schema.json  # draft-7; method_version enum tracks v3a→v3b progression
```

**Dependency footprint:** Core v3a needs only `rapidfuzz` + `scikit-learn` + `numpy` (already
declared or minimal). `imagehash`+`Pillow` (pHash) and `datasketch` (LSH) go behind an optional
`[uil]` extra — keeps v1 install lean.

### Invariants (when implemented)

- Every linkage candidate carries `confidence` (0.0–1.0), `likelihood_ratio`, and
  `feature_evidence` list (min 1 item).
- One-to-one is a **soft** constraint — flag `multi_match_flag: true` on all matches in a
  platform group where >1 link/possible_link; never silently drop.
- `surfaceable = (confidence ≥ 0.7) AND (human_review_status == "approved")`. Gate enforced at
  both Stage 4 emission AND Stage 6 dossier assembly (defense-in-depth).
- `manual_review_required: true` is set on the candidate itself when confidence < 0.7, so
  downstream consumers see the flag even without dossier-level filtering.
- Privacy: LIA must be completed before Stage 4 runs (`compliance.uil_lia_gate()` raises at
  entry); Art. 9-adjacent targets require `consent_record_id` — never surfaceable without it.
- No population-scale linkage; no data writeback to non-GDPR-aligned storage.

---

## 7. Association Graph — Deferred to v2

### Intent

For a set of creator profiles, build a graph where nodes are creators and edges represent
audience overlap, content similarity, or mutual collaboration, enabling:
- Similar-creator discovery (lookalike)
- Campaign reach de-duplication
- Community / niche cluster detection

### Method design (for future implementation)

**Nodes:** Creator profiles (normalized, Stage 2 output).

**Edges (three types):**

| Edge type | Computation | Academic basis |
|---|---|---|
| Audience overlap | Jaccard on follower intersection (if accessible) or cosine similarity on audience attribute vectors | IQFluence 2025; Influencity; audience overlap inferred at ~70–85% accuracy |
| Content similarity | Cosine similarity of niche + hashtag + caption embedding vectors | WWW 2020 multimodal profiling; arXiv:1901.05949 |
| Collaboration | Mutual @mentions, co-tagged posts, co-sponsored brand | Computed from media corpus |

**Community detection:** Leiden algorithm (Traag et al. 2019) — preferred over Louvain because
it guarantees connected communities and locally optimal partitions.

**Centrality measures** (Scientific Reports 2020: no single measure dominates; combine):
- Degree centrality (popularity proxy)
- PageRank (recursive importance via follower graph)
- Betweenness centrality (information broker / cross-niche bridge)

**Audience overlap thresholds (IQFluence industry convention):**
- < 20% = ideal for reach campaigns
- 20–40% = acceptable
- 40–60% = conversion campaign (repeated exposure intended)
- > 60% = remarketing / awareness saturation

### Invariants (when implemented)

- Audience overlap marked as `method: inferred` unless computed from exact follower sets.
- De-duplicated reach estimates carry confidence interval.
- Graph operations require ≥ 2 creator profiles.

---

## 8. Unified Dossier & Scoring

### Intent

Assemble the outputs of all completed stages into a single unified dossier document with:
- Complete creator identity and snapshot metrics
- Full feature set (with confidence + signals)
- Explicit placeholders for deferred stages (linkage, associations)
- Per-feature and composite scores
- Compliance flags
- Human-readable `report.md` rendering

### Composite scores (Stage 6, v1)

All scores: 0–100 range, integer (`int(round(clamp(raw, 0, 100)))`). Every score has a
`signals` list (`min_length=1` enforced at the type level by `DossierScore.signals`) and
`confidence` (mean confidence of contributing features that were actually present; absent
features excluded from the mean but add an `"<feature_id> unavailable"` signal entry).

**No TBD values:** uncomputed or unavailable fields are represented as `"deferred"` or `null`;
never omitted. Idempotency: two runs on identical inputs produce identical dossiers except for
`generated_at` (timestamp) and `dossier_id` (ULID — from `ulid-py`).

**Score weights are named constants** in `pipeline/stage6_dossier.py` (e.g. `EQS_WEIGHTS = {...}`)
so they are parameterizable in tests.

**Engagement Quality Score (EQS):**

```python
TIER_BENCHMARK_ER = {  # midpoint of spec ranges
    "Nano": 11.5, "Micro": 4.4, "Mid": 0.73,
    "Macro": 1.02, "Mega": 1.10, "Celebrity": 1.20
}
EQS_WEIGHTS = {"er": 0.40, "comments": 0.20, "consistency": 0.20, "ratio": 0.20}

er_component        = clamp((er_by_followers / TIER_BENCHMARK_ER[tier]) * 50)
                      # at benchmark → 50; at 2× benchmark → 100
comments_component  = clamp((comments_per_post_avg / 30.0) * 100)
consistency_component = posting_consistency_score * 100       # already [0,1]
ratio_component     = _ratio_reasonableness(follower_following_ratio)
                      # r<0.1→20; r<1→r*100; 1≤r≤50→100; r>50→clamp(100-(r-50)*0.5)

raw = sum(EQS_WEIGHTS[k]*v for k,v in zip(["er","comments","consistency","ratio"],
          [er_component, comments_component, consistency_component, ratio_component]))
if comment_pod_signal == "detected": raw -= 20
EQS = int(round(clamp(raw, 0, 100)))
```

**Authenticity Score:**

```python
AUTH_WEIGHTS = {"completeness": 0.25, "ratio": 0.25}  # 50-pt neutral baseline for unweighted half

raw = 0.25*completeness_component + 0.25*ratio_component + 0.50*50
if engagement_anomaly == "spike":    raw -= 20
if comment_pod_signal == "detected": raw -= 30
Authenticity = int(round(clamp(raw, 0, 100)))
```

*(§8 names only 50% positive weight; a 50-point neutral baseline means a clean profile with
healthy ratio scores ~75; penalties then subtract. Alternative: renormalize named components to
100% — decision for v1 implementation, document in code comment.)*

**Sponsorship Transparency Score:**
- `ftc_disclosure_status`: compliant=100, partial=60, at_risk=20, unknown=50
- Adjusted by ratio of disclosed to total detected sponsored posts

**Brand Safety Score:**
- `caption_sentiment` composition over last 30 posts
- Absence of flagged topics (NLP classifier: hate speech, violence, explicit content, illegal activity)

### Dossier structure (`06-dossier.json`)

```json
{
  "dossier_id": "<ulid>",
  "generated_at": "<ISO UTC>",
  "profile": { "<Stage 2 Profile>" },
  "features": { "<Stage 3 features map>" },
  "scores": {
    "engagement_quality": { "value": 72, "signals": [...], "confidence": 0.85 },
    "authenticity": { "value": 58, "signals": [...], "confidence": 0.70 },
    "sponsorship_transparency": { "value": 90, "signals": [...], "confidence": 0.95 },
    "brand_safety": { "value": 81, "signals": [...], "confidence": 0.80 }
  },
  "linkage": { "status": "deferred", "candidates": [] },
  "associations": { "status": "deferred", "graph_summary": null },
  "compliance_flags": {
    "gdpr_basis": "LEGITIMATE_INTERESTS",
    "art22_applies": true,
    "art22_human_review_required": true,
    "art9_features": ["<feature_ids with art9_risk: true>"],
    "ftc_disclosure_status": "compliant",
    "tos_compliant_source": true,
    "opt_out_path": "DELETE /profiles/{handle}"
  },
  "provenance": {
    "source_id": "sample",
    "pipeline_version": "0.1.0",
    "stages_run": ["ingest", "normalize", "features", "dossier"],
    "stage_artifacts": {
      "01": "projects/<handle>/01-raw.json",
      "02": "projects/<handle>/02-normalized.json",
      "03": "projects/<handle>/03-features.json",
      "06": "projects/<handle>/06-dossier.json"
    }
  }
}
```

### `report.md` structure

Human-readable summary:
1. Creator identity + snapshot (handle, tier, niche, bio)
2. Engagement quality (EQS, ER benchmarked to tier, posting cadence)
3. Content profile (primary/secondary niche, brand affinity, sponsorship history)
4. Authenticity signals (heuristic-level, clearly labeled as incomplete without follower data)
5. Compliance summary (GDPR basis, Art. 22 note, FTC status)
6. Deferred analyses (linkage, audience overlap — with explanation of what they would show)
7. Provenance + confidence notes

---

## 9. Compliance & Ethics

### Implementation shape

Compliance logic lives in `pipeline/compliance/` (subpackage for testability, not a single file).
Tests live in `tests/compliance/`. **Defaults always err on the side of privacy and compliance.**
Compliance annotations appear on ALL stage outputs (intermediate and final), not just the dossier.

```
pipeline/compliance/
├── __init__.py           # re-exports public API
├── tos.py                # enforce_tos_gate, build_governance_block
├── art9.py               # Art9Scanner (defense-in-depth: re-asserts flag over LLM output)
├── art22.py              # art22_applies, build_compliance_flags, assert_scores_explainable
├── fairness.py           # strip_forbidden_features, assert_demographic_inference_humility
└── erasure.py            # erase_profile, is_expired, assert_within_retention, gc_sweep

config.yml (project-level, not env-var only):
  compliance:
    lia_file_path: null       # path to LIA document; checked for existence (not content)
    expose_art9: false        # opt-in to expose Art.9 inferences in report.md
    allow_noncompliant: false # production must be false; tests may override
    default_retention_days: 90
```

**LIA presence check:** `compliance.tos.lia_gate(handle, governance)` checks that `config.lia_file_path` is non-null and the file exists before Stage 4 (UIL) runs; warns (not raises) for Stage 1–3 on Legitimate-Interests basis. Production gate for EU-resident profiles.

**CLI subcommands:**
```bash
python3 profile_analyst.py erase --handle <handle> [--dry-run]  # Art.17 erasure
python3 profile_analyst.py gc     # sweep projects/*/; erase expired artifacts
```

**Boundary invocations:**
1. Stage 1 entry: `enforce_tos_gate(adapter)` → `build_governance_block(adapter, ...)`
2. Stage 2 entry: `assert_within_retention(gov, handle)` + `assert_governance_complete(gov)`
3. Stage 3 exit: `strip_forbidden_features` → `assert_demographic_humility` → `Art9Scanner().enforce`
4. Stage 6 assembly: `assert_scores_explainable(scores)` → `build_compliance_flags(...)` → `gate_art9_report_exposure`

### §9.1 GDPR

**Art. 6 — Lawful basis:** For B2B influencer marketing analytics of public profiles:
- **Legitimate Interests (Art. 6(1)(f))** is the primary basis. Requires a Legitimate Interests
  Assessment (LIA) documented at `config.compliance.lia_file_path` before production use with
  EU-resident profiles.
- **Consent (Art. 6(1)(a))** required for: private analytics (Stories, Reels insights), audience
  demographics, any Art. 9 category inference.

**Art. 9 — Special category data:** Inferred attributes that may reveal health, sexual orientation,
religion, or political views require **explicit consent** or an Art. 9(2) exception. This system:
- `Art9Scanner.enforce()` **re-asserts `art9_risk: true`** for any feature matching the Art.9
  lexicon — even if the LLM (Stage 3) missed it. Defense-in-depth: A9 is a deterministic
  code guarantee, not a probabilistic LLM promise.
- Applies to: feature_ids `primary_niche`, `secondary_niches`, `caption_sentiment`,
  `brand_affinity_signals`; value-level matching against niche lexicons (health, sexuality,
  religion, political); text-pattern scan on `value` and `notes` fields.
- Never emits binary gender or ethnicity scores by default (see §9.5).
- Requires `config.compliance.expose_art9: true` to include Art. 9 inferences in `report.md`;
  default is redacted with a `"<redacted: Art.9, opt-in required>"` note.

**Art. 22 — Automated profiling:** Scores used to select or rank creators for campaigns constitute
automated decision-making with significant effects. The dossier always includes:
- `art22_applies: true` when any composite score is present (conservative: all four v1 scores
  are campaign-selection-relevant, so `art22_applies` is always `true` in v1).
- `art22_applies` and `art22_human_review_required` are **coupled** — the pipeline is advisory
  only; a human must confirm any selection decision.
- The `signals` list on every score is the "meaningful explanation of the logic" (Art. 22 §1).
- `assert_scores_explainable(scores)` raises `ComplianceError` if any score has an empty
  `signals` list — Art.22 cannot be satisfied without it.

**Data minimization (Art. 5(1)(c)):** Collect only fields actually used downstream. Raw API
responses are not stored beyond their source stage artifact. Retention: default 90 days for
scraped/sample data; consent-based data follows adapter's `max_retention_days`.

**Data subject rights (Art. 17 — erasure):** `erase_profile(handle)` deletes `projects/<handle>/`
recursively; returns `ErasureReceipt` for audit. CLI: `python3 profile_analyst.py erase --handle`.
Path-traversal guard: `_safe_handle()` rejects `/`, `..`, absolute paths. Idempotent.

`gc_sweep()` walks `projects/*/02-normalized.json`, reads `retention_expires_at`, and erases
expired profiles. CLI: `python3 profile_analyst.py gc`.

### §9.2 CCPA / CPRA

- CPRA ADMT Regulations (adopted 2025, effective **2026-01-01**) may apply to influencer
  selection systems. Pre-use risk assessments and opt-out rights required.
- The `opt_out_path` in the compliance block serves as the CCPA opt-out mechanism.
- Publicly available information exemption applies to public profile data; does not apply to
  inferred sensitive attributes.

### §9.3 FTC Endorsement Guides

The pipeline detects and reports on sponsorship disclosure. It does NOT enforce compliance —
it surfaces evidence for human review. The `ftc_disclosure_status` field in the dossier reflects
the creator's historical disclosure pattern.

Penalty reference: ~$53,088 per undisclosed sponsorship violation (2025, adjusted annually).

### §9.4 ToS & Scraping Posture

**v1 (SampleAdapter):** No live data fetching. No ToS considerations.

**Future adapters — posture framework:**

| Source type | ToS posture | Implementation gate |
|---|---|---|
| Instagram Graph API (official) | Fully compliant | `tos_compliant: True`; no gate |
| Phyllo / InsightIQ (consent-based) | Fully compliant; creator-consented | `tos_compliant: True`; requires consent flow |
| Logged-off public scraping | Legal under US CFAA post-*Van Buren* (2021) and *Meta v. Bright Data* (2024); contract risk remains; GDPR Legitimate Interests basis required | `tos_compliant: False` by default; requires `ALLOW_NONCOMPLIANT=true` AND a documented LIA |
| Authenticated / logged-in scraping | Almost certainly violates Instagram ToS; not recommended | Not shipped |

### §9.5 Fairness & Bias

Per Buolamwini & Gebru (2018): commercial classifiers exhibit intersectional bias.

- Any demographic inference (age group, gender) must never be presented as ground truth.
- All inferred demographic features carry `confidence < 1.0` and `method: inferred`.
- Binary gender classification is disabled by default; use `audience_gender_skew` (continuous
  scale) rather than a binary label.
- Race / ethnicity inference is disabled entirely — the risk of harm exceeds the utility.
- Niche classifiers trained primarily on English/US data may underperform on non-English
  creators; this limitation is surfaced in `report.md` when `content_language != "en"`.

---

## 10. Schemas & Validation

All stage output JSON files are validated against their schema before the next stage runs.
Schemas live in `schemas/` and follow JSON Schema draft-7.

| Stage | Schema file | Key required fields |
|---|---|---|
| Stage 1 | `01-raw.schema.json` | `handle`, `platform`, `_governance`, `raw_profile`, `raw_media` |
| Stage 2 | `02-normalized.schema.json` | `handle`, `followers`, `following`, `post_count`, `snapshot_at`, `media`, `governance` |
| Stage 3 | `03-features.schema.json` | `profile_handle`, `computed_at`, `features` (array of Feature objects with `feature_id`, `value`, `confidence`, `method`, `signals`) |
| Stage 6 | `06-dossier.schema.json` | `dossier_id`, `generated_at`, `profile`, `features`, `scores`, `compliance_flags`, `provenance` |

`make validate` runs `tools/validate.py` which checks:
1. All `*.schema.json` files are valid JSON Schema.
2. All `specs/*/metadata.yml` have required fields: `id`, `title`, `status`, `owner`,
   `decisions`, `acceptance`.

Schema validation failure is a hard error — the pipeline halts with a clear error message
indicating the failing field and the schema constraint.

---

## 11. Sequencing (v1 → v3)

### v1 (this spec)
- Stages 1 → 2 → 3 → 6 (single Instagram profile, SampleAdapter)
- Feature catalog: §5.1 engagement + §5.2 posting + §5.3 content niche (NLP) + §5.5 sponsored
  detection + §5.6 authenticity heuristics + §5.4 brand affinity
- Composite scores: EQS, Authenticity, Sponsorship Transparency, Brand Safety
- Compliance layer: ToS-gate, governance metadata, Art.22 flags, Art.9 flags, FTC status

### v2 (next)
- Stage 5 — Association Graph: audience overlap (inferred), content similarity graph,
  community detection (Leiden), lookalike discovery
- InstagramGraphAdapter — official API, Business/Creator accounts + `business_discovery`
- Audience demographics (via creator-consent OAuth flow, Phyllo adapter)
- Multi-profile operations: overlap matrix, de-duplicated reach

### v3 (future)
- Stage 4 — Cross-platform Identity Linkage (UIL):
  - v3a: rule/heuristic (username + profile attribute matching)
  - v3b: supervised embedding (PALE-style anchor pairs)
- Multi-platform dossier: Instagram + TikTok + YouTube unified profile
- Deep fake-follower analysis (Botometer-style on follower sample; Cresci digital-DNA for
  coordinated campaign detection)
- Audience demographic inference (for profiles without creator consent, clearly marked inferred)

---

## 12. Acceptance Criteria

See `metadata.yml` for the full testable acceptance register (A1–A9). Summary:

| # | Criterion | Stage |
|---|---|---|
| A1 | `make validate` passes — schemas and metadata valid | all |
| A2 | Full pipeline run on sample handle produces schema-valid artifacts for stages 1,2,3,6 + `report.md` | all |
| A3 | ER by followers computes correctly (exact numeric match on fixture) | Stage 3 |
| A4 | ≥1 sponsored post detected on a fixture with explicit #ad | Stage 3 |
| A5 | Primary niche assigned with confidence ≥ 0.5, method: llm | Stage 3 |
| A6 | Re-running stage 2 overwrites only 02-normalized.json | Stage 2 |
| A7 | SampleAdapter governance fields complete; ToS-gate rejects non-compliant adapter | Stage 1 |
| A8 | Every dossier score has non-empty signals list; compliance_flags present | Stage 6 |
| A9 | Art.9-risk features carry `art9_risk: true` | Stage 3 |

---

## 13. Decisions (locked)

Decisions D1–D12 are maintained in `metadata.yml` (machine-readable). Summary table:

| # | Decision | Basis |
|---|---|---|
| D1 | Unified dossier = linkage + graph + attributes, sequenced | User scope decision |
| D2 | Source-agnostic SourceAdapter ABC; v1 = SampleAdapter | API reality post-Dec 2024 |
| D3 | Staged idempotent pipeline | carrosel-generation proven pattern |
| D4 | Compliance cross-cutting and first-class | GDPR/FTC/ToS legal exposure |
| D5 | v1 = narrow: Stages 1-3+6 only | Start narrow, expand safely |
| D6 | Claude NLP + networkx/Leiden + rapidfuzz | Literature-grounded methods |
| D7 | No live scraping in v1 | Meta v. Bright Data (2024) posture |
| D8 | Explainable scoring (signals list on every score) | GDPR Art.22 requirement |
| D9 | SDD spec format matching OS conventions | Enables ensemble + finalizer skills |
| D10 | Hybrid ensemble refinement on §6, §8, §9 | External model cost/exposure balance |
| D11 | No binary gender/ethnicity by default; Art.9 flagging | Buolamwini & Gebru 2018; GDPR Art.9 |
| D12 | claude-sonnet-4-6 with prompt caching for Stage 3 | InstaSynth F1≈0.93; cost efficiency |

---

## 14. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Instagram data hard to obtain compliantly | Limits live use in v1 | v1 uses sample/user-provided data; live adapters deferred and ToS-gated; legal posture documented |
| Profiling real people → GDPR/CCPA exposure | Regulatory, reputational | Compliance layer first-class; Art.22 human-review required; explainable scores; data minimization |
| Inferred attributes biased/unfair | Discriminatory outcomes | Buolamwini & Gebru cited; flag inferred fields; disable ethnicity inference; expose confidence |
| Audience demographics not truly available via API | Misleading analytics | Mark as inferred with confidence; never present as first-party; defer to v2 with consent flow |
| Ensemble sends spec content to external models | IP / confidentiality | Hybrid: only 3 sections; user opted in explicitly |
| Over-scoping v1 | Delayed delivery | YAGNI: Stages 4-5 explicitly deferred; v1 = single profile only |
| LLM niche classification inconsistent across runs | Feature instability | Prompt caching + structured JSON output; seed validation tests on fixture |
| Art.9 inferences surface unexpectedly | GDPR violation | `art9_risk` flag on every feature; compliance_flags in dossier; opt-out path |

---

## 15. References

Academic and official sources are catalogued in full in
`docs/research/2026-05-29-social-media-associations.md`.

Key citations:

1. Shu, K., et al. (2017). UIL Review. *ACM SIGKDD Explorations* 18(2). DOI: 10.1145/3068777.3068781
2. Senette, C., et al. (2024). UIL Review. *IEEE Access* 12. arXiv: 2409.08966
3. Narayanan, A., & Shmatikov, V. (2009). De-anonymizing Social Networks. *IEEE S&P 2009*. arXiv: 0903.3276
4. Zafarani, R., & Liu, H. (2013). MOBIUS. *KDD 2013*. DOI: 10.1145/2487575.2487648
5. Liu, L., et al. (2016). IONE. *IJCAI 2016*.
6. Man, T., et al. (2016). PALE. *IJCAI 2016*.
7. Zhou, F., et al. (2018). DeepLink. *IEEE INFOCOM 2018*.
8. Vosoughi, S., et al. (2015). Digital Stylometry. *SocInfo 2015*. arXiv: 1605.05166
9. Traag, V. A., et al. (2019). Leiden algorithm. *Scientific Reports* 9. DOI: 10.1038/s41598-019-41695-z
10. Blondel, V. D., et al. (2008). Louvain algorithm. *J. Stat. Mech.* DOI: 10.1088/1742-5468/2008/10/P10008
11. Fellegi, I. P., & Sunter, A. B. (1969). Record Linkage theory. *JASA* 64(328).
12. Papadakis, G., et al. (2020). Blocking for ER. *ACM CSUR* 53(2). DOI: 10.1145/3377455
13. Kosinski, M., et al. (2013). Private traits. *PNAS* 110(15). DOI: 10.1073/pnas.1218772110
14. Buolamwini, J., & Gebru, T. (2018). Gender Shades. *FAT* 2018*, PMLR 81.
15. Varol, O., et al. (2017). Botometer. *ICWSM 2017*. arXiv: 1703.03107
16. Cresci, S., et al. (2017). Social Fingerprinting. *IEEE TDSC*. arXiv: 1703.04482
17. Granovetter, M. S. (1973). Strength of Weak Ties. *AJS* 78(6). DOI: 10.1086/225469
18. McPherson, M., et al. (2001). Homophily. *Annual Review Sociology* 27. DOI: 10.1146/annurev.soc.27.1.415
19. Liben-Nowell, D., & Kleinberg, J. (2007). Link prediction. *JASIST* 58(7). DOI: 10.1002/asi.20591
20. "Multimodal Post Attentive Profiling." *WWW 2020*. https://dl.acm.org/doi/fullHtml/10.1145/3366423.3380052
21. "InstaSynth." *ICWSM 2024*. https://arxiv.org/html/2403.15214v1
22. Meta v. Bright Data ruling (2024-01-23). N.D. Cal. Case 3:23-cv-00077-EMC.
23. FTC Endorsement Guides (eff. Oct 2023). https://www.ftc.gov/business-guidance/advertising-marketing/endorsements-influencers-reviews
24. GDPR Art. 22. https://gdpr-info.eu/art-22-gdpr/
25. Meta Instagram Platform Docs. https://developers.facebook.com/docs/instagram-platform/overview/

---

*End of Spec 0001 v1.0 — draft*
