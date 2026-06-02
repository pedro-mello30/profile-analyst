# Spec 0015 — Dossier Cross-Platform Synthesis

Status: draft · Date: 2026-06-02 · Method: Spec-Driven Development

---

## 0. Philosophy (SDD)

This spec describes **what** and **why**, separated from **how**. Each section defines:

1. **Intent** — purpose of the component.
2. **Inputs** — format and expected structure.
3. **Outputs** — format and structure produced.
4. **Invariants** — rules that may never be violated.
5. **Failure modes** — what counts as failure; what the component does NOT do.

The implementation lives in `pipeline/stage6_dossier.py` and
`pipeline/enrichment/platform_presence.py`; this spec is the source of truth.

---

## 1. Problem

Stage 6 (Dossier) currently reads only Stage 3 features and Stage 1 governance metadata.
It produces a thin report: a single niche label, one engagement metric, and scores backed
exclusively by Instagram signals.

`enrichment_map.json`, produced by Stage 1B (spec 0014), contains cross-platform signals
— YouTube subscriber counts, podcast episode counts, GitHub repos — that Stage 6 completely
ignores. A creator like `@filipelauar` is reported as *"Travel, Micro, 1,703 followers"*
when the fuller picture is an AI/tech podcaster with a 38-episode podcast and 4,200 YouTube
subscribers.

The root cause: there is no stage that reads `enrichment_map.json` and renders its signals
into the dossier.

---

## 2. Goals / Non-Goals

### Goals

- Stage 6 reads `enrichment_map.json` (if present) and renders a new **Platform Presence**
  section in `report.md` with a structured table and a template-generated narrative.
- The narrative is **purely factual** — assembled from signal values, no inference or
  interpretation.
- The **Enrichment Uplift** advisory block names the platforms found and states which scores
  are Instagram-only — no qualitative claims.
- One row per platform in the table (**deduplication**): when multiple adapters contribute
  signals for the same platform, the row uses the highest-confidence signal; all contributing
  adapters are listed in `sources[]`.
- Each platform row in `06-dossier.json` carries explicit `confidence` and `sources[]` fields.
- Existing scores (EQS, Brand Safety, Sponsorship Transparency) and the tier label are
  **not recalculated** — this spec is purely additive.
- `PlatformPresenceExtractor.extract()` is a **pure function** — no I/O, fully unit-testable.
- If `enrichment_map.json` is absent, Stage 6 runs identically to current behavior.

### Non-Goals

| Out of scope | Reason | Target |
|---|---|---|
| Score recalculation from enrichment signals | Deferred — natural follow-on spec | future |
| LLM synthesis of narrative | Deliberately excluded — templates only, zero extra cost | never |
| Changes to Stage 1B / spec 0014 behavior | This spec is read-only on enrichment_map | n/a |
| Surfacing OSINT signals by default | Requires `--expose-osint` flag per spec 0014 §9 | design |

---

## 3. Inputs

### 3.1 Primary input: `enrichment_map.json`

Produced by Stage 1B (spec 0014). Shape relevant to this spec:

```json
{
  "handle": "filipelauar",
  "signals": [
    {
      "key": "youtube_subscriber_count",
      "value": 4200,
      "unit": "count",
      "confidence": 1.0,
      "method": "api",
      "source": "youtube",
      "osint_risk": false
    }
  ],
  "compliance": {
    "osint_signals_present": true
  }
}
```

Stage 6 reads `signals[]` only. It does not read `entity_pool[]` or `adapter_runs[]`.

### 3.2 Existing Stage 6 inputs (unchanged)

- `03-features.json` — niche, engagement, LLM features
- `02-normalized.json` — governance metadata, handle, display name

---

## 4. Signal → Platform Mapping

The extractor maps signal keys to platform rows via a static lookup table. No inference.

| Signal key | Platform | Display metric template |
|---|---|---|
| `youtube_subscriber_count` | YouTube | `{value} subscribers` |
| `youtube_video_count` | YouTube | `{value} videos` |
| `podcast_episode_count` | Podcast | `{value} episodes` |
| `podcast_last_episode_at` | Podcast | `Last: {value[:7]}` (YYYY-MM) |
| `spotify_follower_count` | Spotify | `{value} followers` |
| `github_public_repos` | GitHub | `{value} public repos` |
| `github_followers` | GitHub | `{value} followers` |
| `twitch_follower_count` | Twitch | `{value} followers` |
| `reddit_karma_total` | Reddit | `{value} karma` |
| `substack_post_count` | Substack | `{value} posts` |
| `maigret_platform_hits[]` | (presence only) | `confirmed present` |

**Row inclusion rule:** a platform row is emitted only when ≥1 of its signals has
`confidence ≥ 0.7` and `osint_risk: false` (or `--expose-osint` is passed).

**Deduplication rule:** one row per platform. When multiple adapters contribute signals
for the same platform, the row uses the signal with the highest `confidence`. All
contributing adapter `source` values accumulate in `rows[].sources[]`.

**Key metric assembly:** multiple signals for the same platform are joined with ` · ` in
display order defined by the mapping table above (top-to-bottom = left-to-right in display).

---

## 5. Output

### 5.1 `report.md` — new section 8

Rendered only when ≥1 platform row qualifies.

```markdown
## 8. Platform Presence

> ⬆ Enrichment Uplift: 3 additional platforms detected via Stage 1B (podcast, youtube, github).
> EQS, Brand Safety, and Sponsorship Transparency scores are based on Instagram data only.

| Platform | Handle / ID         | Key Metric                          |
|----------|---------------------|-------------------------------------|
| Podcast  | lifewithai (iTunes) | 38 episodes · Last: 2026-05         |
| YouTube  | @filipelauar        | 4,200 subscribers · 61 videos       |
| GitHub   | filipelauar         | 12 public repos · 47 followers      |

@filipelauar has a confirmed presence on 3 platforms beyond Instagram.
Podcast: 38 episodes published (iTunes). YouTube: 4,200 subscribers, 61 videos.
GitHub: 12 public repos, 47 followers.
```

**Narrative template:**

```python
INTRO = "{handle} has a confirmed presence on {count} platform(s) beyond Instagram."

PER_PLATFORM = {
    "podcast":  "Podcast: {count} episodes published (iTunes).",
    "youtube":  "YouTube: {subs} subscribers, {videos} videos.",
    "github":   "GitHub: {repos} public repos, {followers} followers.",
    "twitch":   "Twitch: {followers} followers.",
    "substack": "Substack: {posts} posts published.",
    "spotify":  "Spotify: {followers} followers.",
    "reddit":   "Reddit: {karma} karma.",
}
```

Platform order: podcast → youtube → github → substack → spotify → twitch → reddit → others.
No interpretive language ("signals", "confirms", "suggests") — every sentence reports a fact.

If no platform rows qualify, section 8 is omitted entirely. No uplift advisory is shown.

### 5.2 `06-dossier.json` — new `platform_presence` block

```json
"platform_presence": {
  "platforms_found": ["podcast", "youtube", "github"],
  "enrichment_source": "enrichment_map.json",
  "uplift_advisory": true,
  "rows": [
    {
      "platform": "podcast",
      "handle_or_id": "lifewithai (iTunes)",
      "key_metric": "38 episodes · Last: 2026-05",
      "confidence": 1.0,
      "sources": ["itunes", "linktree"]
    },
    {
      "platform": "youtube",
      "handle_or_id": "@filipelauar",
      "key_metric": "4,200 subscribers · 61 videos",
      "confidence": 0.95,
      "sources": ["youtube", "maigret"]
    }
  ]
}
```

- `confidence` per row = max confidence across all contributing signals for that platform.
- `sources[]` = all adapter IDs that contributed ≥1 qualifying signal for that platform.
- When `enrichment_map.json` is absent: `platform_presence` is `{"platforms_found": [], "uplift_advisory": false, "rows": []}`.

### 5.3 Invariants

- **Additive only:** no existing field in `06-dossier.json` or `report.md` is modified.
- **Pure extraction:** `PlatformPresenceExtractor.extract(enrichment_map: dict | None) → PlatformPresenceBlock` has no I/O, no side effects, no global state.
- **OSINT gate:** signals with `osint_risk: true` are excluded from rows unless the caller passes `expose_osint=True`.
- **Confidence floor:** `confidence ≥ 0.7` is the minimum for a signal to contribute to a row.
- **Deduplication:** `platforms_found[]` and `rows[]` contain each platform at most once.
- **Factual narrative:** narrative sentences are assembled from signal values only; no adjectives or verbs that imply quality judgment ("dominant", "strong", "confirms").

### 5.4 Failure modes

- `enrichment_map.json` absent → section 8 omitted, `platform_presence.rows = []`. Not an error.
- `enrichment_map.json` malformed JSON → Stage 6 logs a warning, treats as absent. Not a crash.
- All signals below confidence threshold → section 8 omitted. Not an error.
- Unknown signal key (not in mapping table) → silently skipped; does not block other signals.

---

## 6. Implementation Sketch

### New file: `pipeline/enrichment/platform_presence.py`

```python
@dataclass
class PlatformRow:
    platform: str
    handle_or_id: str
    key_metric: str
    confidence: float
    sources: list[str]

@dataclass
class PlatformPresenceBlock:
    platforms_found: list[str]
    uplift_advisory: bool
    rows: list[PlatformRow]

class PlatformPresenceExtractor:
    @staticmethod
    def extract(
        enrichment_map: dict | None,
        *,
        expose_osint: bool = False,
        min_confidence: float = 0.7,
    ) -> PlatformPresenceBlock:
        ...  # pure function; see mapping table in §4
```

### Modified file: `pipeline/stage6_dossier.py`

```python
from pipeline.enrichment.platform_presence import PlatformPresenceExtractor

enrichment_map = _load_enrichment_map(handle)   # returns None if absent
platform_block = PlatformPresenceExtractor.extract(
    enrichment_map,
    expose_osint=args.expose_osint,
)
dossier["platform_presence"] = asdict(platform_block)
```

### Modified file: `schemas/06-dossier.schema.json`

Add optional `platform_presence` object with `platforms_found`, `uplift_advisory`, `rows`.
`additionalProperties: false` on the row object.

---

## 7. Project Layout

```
pipeline/enrichment/
└── platform_presence.py       (NEW)

pipeline/
└── stage6_dossier.py          (modified)

schemas/
└── 06-dossier.schema.json     (modified — platform_presence block, optional)

specs/0015-dossier-cross-platform-synthesis/
├── spec.md                    (this file)
└── metadata.yml
```

---

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| A1 | Running Stage 6 after Stage 1B with a warm enrichment cache renders `## 8. Platform Presence` in `report.md` |
| A2 | Each platform row appears only when ≥1 signal with `confidence ≥ 0.7` and `osint_risk: false` exists for that platform |
| A3 | The uplift advisory names the platforms found and states that scores are Instagram-only — no interpretive language |
| A4 | Stage 6 output is byte-for-byte identical to current behavior when `enrichment_map.json` is absent |
| A5 | `06-dossier.json` contains `platform_presence.platforms_found[]` and passes `make validate` |
| A6 | OSINT-risk signals are excluded from rows by default; included when `--expose-osint` is passed |
| A7 | `PlatformPresenceExtractor.extract()` is a pure function — unit-testable with no I/O |
| A8 | When two adapters produce signals for YouTube, `platform_presence.rows[]` contains exactly one YouTube row; `sources` lists both adapters |
| A9 | Each row carries `confidence` (max across contributing signals) and `sources[]` (all contributing adapter IDs) |
| A10 | Narrative paragraph contains no interpretive language — every sentence is derived directly from a signal value |
| A11 | Malformed `enrichment_map.json` causes Stage 6 to log a warning and continue; `platform_presence.rows` is `[]` |
| A12 | `make validate` passes after implementation: `06-dossier.schema.json` accepts the new `platform_presence` block and rejects unknown fields inside it |

---

## 9. Dependencies

- **Spec 0014** (Multi-Source Enrichment Engine) — must produce `enrichment_map.json`.
  This spec degrades gracefully when 0014 has not run.
- No new external Python dependencies.
