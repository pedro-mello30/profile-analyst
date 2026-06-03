# Plan 0015 — Dossier Cross-Platform Synthesis

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
Adds cross-platform presence surfacing to Stage 6 by reading `enrichment_map.json` (spec 0014).
Net-new code is confined to `pipeline/enrichment/platform_presence.py` and targeted edits to
`pipeline/stage6_dossier.py` and `schemas/06-dossier.schema.json`.
**No LLM call, no new external dependencies, purely additive to existing Stage 6 output.**

## Architecture (reference)

```
enrichment_map.json
  (from Stage 1B)
        │
        ▼
PlatformPresenceExtractor.extract()     ← pure function, no I/O
        │
        ├─► PlatformPresenceBlock
        │     ├── platforms_found[]
        │     ├── uplift_advisory
        │     └── rows[]
        │           ├── platform
        │           ├── handle_or_id
        │           ├── key_metric
        │           ├── confidence     ← max across contributing signals
        │           └── sources[]      ← all adapter IDs that contributed
        │
        ▼
stage6_dossier.py
        ├─► 06-dossier.json  (platform_presence block added)
        └─► report.md        (## 8. Platform Presence section added)
```

If `enrichment_map.json` is absent: `PlatformPresenceBlock` has empty `rows[]`, `uplift_advisory=false`;
Stage 6 output is byte-for-byte identical to current behavior.

## Tracks

- **Track A — Schema contract.** Update `schemas/06-dossier.schema.json` to add the optional
  `platform_presence` block (`platforms_found[]`, `uplift_advisory`, `rows[]` with
  `additionalProperties: false`). Register in `tools/validate.py`. No behavior change yet.

- **Track B — PlatformPresenceExtractor (parallel with A).** Create
  `pipeline/enrichment/platform_presence.py`: `PlatformPresenceBlock` dataclass,
  `PlatformRow` dataclass, `PlatformPresenceExtractor.extract()` pure function. Implements
  signal→platform mapping, confidence floor (≥0.7), OSINT gate, deduplication (one row per
  platform, max-confidence wins, sources[] accumulated), and factual template narrative.

- **Track C — Stage 6 integration (depends on A+B).** Wire `PlatformPresenceExtractor` into
  `stage6_dossier.py`: load `enrichment_map.json` (None if absent/malformed), call `extract()`,
  write `platform_presence` block to dossier JSON, render `## 8. Platform Presence` section in
  `report.md` (table + uplift advisory + narrative). Handle absent and malformed JSON gracefully.

- **Track D — Tests (depends on B+C).** Unit tests for `PlatformPresenceExtractor.extract()`
  covering: happy path, absent enrichment_map, confidence threshold, OSINT gate, deduplication,
  zero qualifying signals. Integration test for Stage 6: confirms `report.md` section appears /
  is absent based on enrichment_map presence.

Tracks A and B can be done in parallel. C depends on A+B; D depends on B+C.

## Sequencing & PR boundaries

1. **PR-1 (A):** schema update + `make validate` green. No behavior change.
2. **PR-2 (B):** `platform_presence.py` pure function + unit tests.
3. **PR-3 (C):** Stage 6 wiring — `stage6_dossier.py` edits + `report.md` renderer.
4. **PR-4 (D):** Full test suite (unit + integration). `make test` green.

## Risks & mitigations

- **enrichment_map.json absent in existing projects.** → Extractor returns empty block;
  Stage 6 falls back to current behavior; no existing test breaks.
- **enrichment_map.json malformed JSON.** → `_load_enrichment_map()` catches `json.JSONDecodeError`,
  logs a warning, returns `None`; extractor gets `None` and returns empty block.
- **Signal key drift between spec 0014 and 0015.** → Mapping table in `platform_presence.py`
  uses string literals; unknown keys are silently skipped (spec §5.4). Document the coupling in
  a comment pointing to spec 0014 §4 as the authoritative signal key list.
- **Scope creep toward score recalculation.** → Explicitly deferred to the follow-on spec per
  design decision D1; `platform_presence` is a read-only display block.

## Out of scope (this plan)

Score recalculation from enrichment signals, LLM synthesis, any change to Stage 1B / spec 0014
behavior, OSINT exposure by default, and audience-demographics enrichment — all deferred per
spec §2 Non-Goals.
