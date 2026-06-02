# Design: Dossier Cross-Platform Synthesis (Spec 0015)

Date: 2026-06-02 · Status: approved · Author: Pedro Mello

---

## Problem

Stage 6 (Dossier) currently reads only Stage 3 features and Stage 1 governance metadata. It has
no awareness of `enrichment_map.json` produced by Stage 1B (spec 0014). The result: a creator
like `@filipelauar` appears in the report as *"Travel, Micro, 1,703 followers"* — the fuller
picture (AI/tech podcaster, 38 podcast episodes, 4.2K YouTube subscribers) is invisible. Scores
like Brand Safety 90/100 rest on Instagram signals alone and feel undefended to a brand manager.

---

## Goals

1. Stage 6 reads `enrichment_map.json` when present and renders a new **Platform Presence**
   section in `report.md`
2. That section contains: a **structured table** (platform → handle/ID → key metric) plus a
   **template-generated narrative paragraph** — no LLM call
3. When ≥1 platform signal is present, Stage 6 emits an **Enrichment Uplift** advisory block —
   e.g. *"⬆ 3 additional platforms detected; existing scores reflect Instagram data only"*
4. Existing scores (EQS, Brand Safety, Sponsorship Transparency) and the tier label are
   **not recalculated** — this is purely additive
5. If `enrichment_map.json` is absent, Stage 6 runs identically to current behavior

## Non-Goals

- Score recalculation (deferred — natural follow-on spec)
- LLM synthesis (deliberately excluded — templates only)
- Any change to Stage 1B / spec 0014 behavior

---

## Data Flow

```
enrichment_map.json
        │
        ▼
PlatformPresenceExtractor
        │
        ├─► platform_rows[]     → structured table in report.md
        ├─► narrative_text      → template paragraph in report.md
        └─► uplift_advisory     → "⬆ N platforms detected" block
```

`PlatformPresenceExtractor.extract()` is a **pure function**:
`enrichment_map dict → PlatformPresenceBlock dataclass`. No side effects, no I/O.

### Signal → Platform Mapping

| Signal key (from enrichment_map) | Platform | Display metric |
|---|---|---|
| `youtube_subscriber_count` | YouTube | "X subscribers" |
| `youtube_video_count` | YouTube | "+ X videos" |
| `podcast_episode_count` | Podcast | "X episodes" |
| `podcast_last_episode_at` | Podcast | "Last: YYYY-MM" |
| `spotify_follower_count` | Spotify | "X followers" |
| `github_public_repos` | GitHub | "X public repos" |
| `github_followers` | GitHub | "+ X followers" |
| `twitch_follower_count` | Twitch | "X followers" |
| `reddit_karma_total` | Reddit | "X karma" |
| `substack_post_count` | Substack | "X posts" |
| `maigret_platform_hits[]` | (presence only) | "confirmed present" |

A platform row is emitted only when ≥1 signal for that platform is present **and**
`confidence ≥ 0.7`. Low-confidence signals are silently excluded from the table (they remain
in `enrichment_map.json` for downstream machine consumers).

---

## Report Output

### `report.md` — new section 8

```markdown
## 8. Platform Presence

> ⬆ Enrichment Uplift: 3 additional platforms detected via Stage 1B.
> Existing scores (EQS, Brand Safety, Sponsorship Transparency) reflect
> Instagram data only and may understate this creator's full reach.

| Platform | Handle / ID         | Key Metric                          |
|----------|---------------------|-------------------------------------|
| Podcast  | lifewithai (iTunes) | 38 episodes · Last: 2026-05         |
| YouTube  | @filipelauar        | 4,200 subscribers · 61 videos       |
| GitHub   | filipelauar         | 12 public repos · 47 followers      |

Filipe maintains an active multi-platform presence extending beyond Instagram.
A podcast (38 episodes) and YouTube channel (4,200 subscribers) confirm consistent
long-form content production. GitHub activity signals a technical practitioner identity.
```

If no platform signals meet the confidence threshold, the entire section is omitted and no
uplift advisory is shown.

### Template Logic

Narrative paragraph is assembled from sentence fragments — no LLM:

```python
INTRO = "{handle} maintains an active multi-platform presence extending beyond Instagram."

PER_PLATFORM = {
    "podcast":  "A podcast ({count} episodes) confirms consistent audio content production.",
    "youtube":  "A YouTube channel ({subs} subscribers) extends reach into video.",
    "github":   "GitHub activity ({repos} repos) signals a technical practitioner identity.",
    "twitch":   "Twitch presence ({followers} followers) suggests live/gaming content.",
    "substack": "A Substack newsletter ({posts} posts) indicates direct audience ownership.",
    "spotify":  "Spotify presence ({followers} followers) confirms audio/music reach.",
    "reddit":   "Reddit activity ({karma} karma) signals community engagement.",
}
```

Sentences are ordered by platform tier: podcast → youtube → github → substack → others.

### `06-dossier.json` addition

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
      "confidence": 1.0
    }
  ]
}
```

---

## Implementation

### New / modified files

```
pipeline/
└── stage6_dossier.py          (modified — adds platform_block rendering)

pipeline/enrichment/
└── platform_presence.py       (NEW — PlatformPresenceExtractor, PlatformPresenceBlock)

schemas/
└── 06-dossier.schema.json     (modified — platform_presence block, optional field)

specs/0015-dossier-cross-platform-synthesis/
├── spec.md
└── metadata.yml
```

### Stage 6 change (sketch)

```python
# stage6_dossier.py — existing flow unchanged
enrichment_map = load_enrichment_map(handle)           # returns None if absent
platform_block = PlatformPresenceExtractor.extract(enrichment_map)  # None if absent
dossier["platform_presence"] = platform_block or {
    "platforms_found": [],
    "uplift_advisory": False,
    "rows": [],
}
```

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| A1 | Running Stage 6 after Stage 1B with a warm enrichment cache renders a `## Platform Presence` section in `report.md` |
| A2 | Each platform row appears only when ≥1 signal with `confidence ≥ 0.7` exists for that platform |
| A3 | The uplift advisory is absent when `enrichment_map.json` is absent or contains zero qualifying signals |
| A4 | Stage 6 output is byte-for-byte identical to current behavior when `enrichment_map.json` is absent |
| A5 | `06-dossier.json` contains `platform_presence.platforms_found[]` and passes `make validate` |
| A6 | OSINT-sourced platform rows (e.g. Maigret-discovered handles) are excluded unless `--expose-osint` is passed |
| A7 | `PlatformPresenceExtractor.extract()` is a pure function — unit-testable with no I/O |

---

## Dependencies

- **Spec 0014** (Multi-Source Enrichment Engine) — must produce `enrichment_map.json` before
  Stage 6 runs. This spec is additive: 0015 degrades gracefully when 0014 has not run.
- No new external dependencies.
