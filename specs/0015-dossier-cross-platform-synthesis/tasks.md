# Tasks 0015 — Dossier Cross-Platform Synthesis

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A and B can be done in parallel. C depends on A+B; D depends on B+C.
**No LLM call, no new external dependencies, purely additive.**

---

## Track A — Schema contract

- [ ] T1 Open `schemas/06-dossier.schema.json` and add an optional `platform_presence` property:
      top-level object with `platforms_found` (array of strings), `uplift_advisory` (boolean),
      and `rows` (array of row objects). Mark `additionalProperties: false` on the row object.
- [ ] T2 Row object shape: required `platform` (string), `handle_or_id` (string), `key_metric`
      (string), `confidence` (number, 0.0–1.0), `sources` (array of strings, minItems: 1).
- [ ] T3 Register the updated schema in `tools/validate.py` if not already auto-detected; confirm
      `make validate` passes with the new schema and rejects a row with an unknown field.

**Exit (Track A):** `make validate` green with the updated schema; unknown fields in a
`platform_presence` row are rejected.

---

## Track B — PlatformPresenceExtractor

- [ ] T4 Create `pipeline/enrichment/platform_presence.py`. Define `PlatformRow` dataclass:
      `platform`, `handle_or_id`, `key_metric`, `confidence`, `sources: list[str]`.
- [ ] T5 Define `PlatformPresenceBlock` dataclass: `platforms_found: list[str]`,
      `uplift_advisory: bool`, `rows: list[PlatformRow]`.
- [ ] T6 Implement the signal→platform mapping table (spec §4): maps signal keys to platform
      slugs and display metric templates. Store as a module-level constant (no I/O).
- [ ] T7 Implement `PlatformPresenceExtractor.extract(enrichment_map, *, expose_osint=False,
      min_confidence=0.7) -> PlatformPresenceBlock`. Logic:
      1. Return empty block when `enrichment_map` is `None`.
      2. Iterate `signals[]`; skip keys not in the mapping table and signals below
         `min_confidence` or with `osint_risk: true` (unless `expose_osint=True`).
      3. Group matching signals by platform slug.
      4. Per platform: assemble `key_metric` by joining display fragments in mapping-table order;
         `confidence = max(signal.confidence for signal in group)`;
         `sources = sorted(set(signal.source for signal in group))`.
      5. Build `handle_or_id` from the first available handle/id signal for that platform
         (platform-specific lookup, e.g. `youtube_handle` → YouTube, `podcast_itunes_id` → Podcast).
      6. Order rows by platform tier (podcast → youtube → github → substack → spotify →
         twitch → reddit → others).
      7. Set `uplift_advisory = len(rows) > 0`.
      8. Return `PlatformPresenceBlock`.
- [ ] T8 Unit tests `tests/enrichment/test_platform_presence.py`:
      - Happy path: enrichment_map with youtube + podcast signals → two rows, correct metrics,
        `uplift_advisory=True`.
      - `None` input → empty block, `uplift_advisory=False`.
      - Signal below confidence floor → row excluded.
      - `osint_risk: true` signal excluded by default; included when `expose_osint=True`.
      - Deduplication: two adapters produce `youtube_subscriber_count` → one YouTube row;
        `sources` lists both adapters; `confidence` is the max.
      - Zero qualifying signals → empty block, section absent.
      - Unknown signal key → silently skipped, does not crash.

**Exit (Track B):** all unit tests pass; `extract()` has no I/O and no side effects.

---

## Track C — Stage 6 integration (depends on A+B)

- [ ] T9 Add `_load_enrichment_map(handle: str, project_dir: Path) -> dict | None` to
      `pipeline/stage6_dossier.py`: reads `projects/{handle}/enrichment_map.json`; returns
      `None` if file absent; catches `json.JSONDecodeError`, logs a warning at `WARNING` level,
      returns `None`.
- [ ] T10 In `stage6_dossier.run()`, after existing score computation, call:
      ```python
      enrichment_map = _load_enrichment_map(handle, project_dir)
      platform_block = PlatformPresenceExtractor.extract(
          enrichment_map, expose_osint=args.expose_osint
      )
      dossier["platform_presence"] = dataclasses.asdict(platform_block)
      ```
- [ ] T11 In `report.md` renderer, add `## 8. Platform Presence` section immediately before the
      final provenance block. Render only when `platform_block.rows` is non-empty:
      - Uplift advisory block (factual: names platforms, states scores are Instagram-only).
      - Markdown table: Platform | Handle / ID | Key Metric.
      - Narrative paragraph: INTRO sentence + one sentence per platform in tier order
        (factual templates only, no interpretive language).
- [ ] T12 When `platform_block.rows` is empty, omit section 8 entirely. No advisory shown.
- [ ] T13 Verify existing Stage 6 tests still pass unmodified when `enrichment_map.json` is absent
      from the test fixture directory — confirming the additive / non-breaking invariant.

**Exit (Track C):** `report.md` renders section 8 when signals qualify; section is absent when
enrichment_map is absent; `06-dossier.json` carries `platform_presence` block; existing tests
pass unchanged.

---

## Track D — Tests (depends on B+C)

- [ ] T14 Integration test `tests/test_stage6_platform_presence.py`: fixture with a valid
      `enrichment_map.json` (youtube + podcast signals, confidence ≥ 0.7) → Stage 6 run produces
      `report.md` containing `## 8. Platform Presence` and a table with two rows.
- [ ] T15 Integration test: fixture *without* `enrichment_map.json` → Stage 6 output is
      byte-for-byte identical to the output produced without spec 0015 changes
      (confirms A4 from acceptance criteria).
- [ ] T16 Integration test: fixture with malformed `enrichment_map.json` (invalid JSON) → Stage 6
      completes without raising; `platform_presence.rows` is `[]` in `06-dossier.json`; a
      `WARNING`-level log line is emitted.
- [ ] T17 Integration test: `--expose-osint` flag → OSINT-risk signals appear in rows;
      without the flag they are absent.
- [ ] T18 Confirm `make validate` passes end-to-end with the produced `06-dossier.json` including
      the `platform_presence` block.

**Exit (Track D):** `make test` green; `make validate` green; all four integration scenarios covered.
