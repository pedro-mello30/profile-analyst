# Plan 0002 — Neo4j Graph Persistence

Derived from `spec.md`. Single-PR-per-track landing; tracks are dependency-ordered.
This spec adds **Stage 7 LOAD** on top of the existing 0001 pipeline (Stages 1–3 + 6).
It does **not** modify any 0001 stage. JSON artifacts remain the document/audit store;
Neo4j is the graph store. **No GDS plugin** (algorithms deferred to spec 0004).

## Architecture (reference)

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                   profile_analyst.py  (CLI)                       │
  │  --handle <ig>  --stage all|7   load                             │
  └──────────┬───────────────────────────────────────────────────────┘
             │  (Stages 1→2→3→6 from spec 0001 produce JSON artifacts)
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  Stage 7  LOAD          pipeline/stage7_load.py                  │
  │  read 02/03/05?/06 JSON → build graph batches                    │
  │  ensure_constraints → supersede prior run → MERGE entities       │
  │  → MERGE Signal/Score (run_id) → MERGE edges                     │
  │  → 07-load-manifest.json (validated: 07-graph-load.schema.json)  │
  └──────────┬──────────────────────────────────────────────────────┘
             │
  ┌──────────▼──────────────────────────────────────────────────────┐
  │  Neo4j 5.x (Community)        bolt://localhost:7687              │
  │  Creator · Media · Comment · User · Demographic · Signal · Score │
  └─────────────────────────────────────────────────────────────────┘

  Read side: pipeline/graph/queries.py — AQ1..AQ4 (Art.22, overlap, Art.9, FTC)
  Driver:    official `neo4j` Python driver, parameterized Cypher, write tx
```

Stage 7 is **idempotent**: re-running for a handle yields identical node/edge counts.
Entities are MERGEd on natural keys; Signal/Score nodes are versioned by `run_id` and
prior-run versions are superseded each run.

## Implementation tracks (dependency-ordered)

### Track A — Schema, config, driver plumbing (foundation)

- Write `schemas/07-graph-load.schema.json` (draft-7) for `07-load-manifest.json`:
  required `run_id`, `handle`, `loaded_at`, `neo4j_database`, `counts`
  (`nodes` + `relationships` maps), `associations` (`loaded` | `deferred`),
  `superseded` (counts of removed prior-run Signal/Score).
- Extend `tools/validate.py` so `make validate` checks the new schema.
- Add the `neo4j` driver dependency to `pyproject.toml`.
- Add env config: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` (optional).
- Add `make load HANDLE=<handle>` target.

**Exit:** `make validate` green with the new schema; driver imports cleanly.

---

### Track B — Graph connection + constraints (depends on A)

- Write `pipeline/graph/__init__.py` and `pipeline/graph/connection.py`:
  a thin `GraphSession` wrapper around the official driver (context manager,
  parameterized `execute_write` / `execute_read` helpers).
- Write `pipeline/graph/constraints.py` — `ensure_constraints(session)` runs the
  `CREATE CONSTRAINT ... IF NOT EXISTS` / `CREATE INDEX ... IF NOT EXISTS` set from
  spec §5.3. Idempotent; safe to run every load.

**Exit:** against a local Neo4j, `ensure_constraints` runs twice with no error and
the four uniqueness constraints + score index exist.

---

### Track C — Mappers: JSON artifact → graph batches (depends on A)

- Write `pipeline/graph/mappers.py` — pure functions, no I/O, fully unit-testable:
  - `creator_from_normalized(doc) -> dict` (incl. governance props)
  - `media_from_normalized(doc) -> list[dict]`, `comments_from_media(...)`,
    `users_from_comments(...)`
  - `signals_from_features(doc, run_id) -> list[dict]` (carry `confidence`,
    `method`, `art9_risk`, `source`, `computed_at`)
  - `scores_from_dossier(doc, run_id) -> list[dict]` + `contributions(...)` (the
    `CONTRIBUTED_TO {weight}` edges from each score's `signals[]`)
  - `associations_from_graph(doc)` — returns `(edges, "loaded")` or `([], "deferred")`
    when `05-graph.json` is absent.

**Exit:** unit tests map each fixture artifact to the expected batch dicts; missing
`05-graph.json` yields `deferred`.

---

### Track D — Stage 7 LOAD orchestrator (depends on B, C)

Write `pipeline/stage7_load.py`. Orchestrates:
1. Resolve `run_id` (UUID), `loaded_at` (UTC ISO).
2. Load JSON artifacts (`02`, `03`, optional `05`, `06`) for the handle.
3. **Compliance gate:** `assert_governance_complete(creator_props)` — fail unless
   `--allow-noncompliant` (mirrors spec 0001 Stage 1 gate, reuses
   `pipeline.compliance`).
4. `ensure_constraints(session)`.
5. **Supersede:** detach-delete prior-run `Signal`/`Score` for the creator
   (`run_id <> $run_id`).
6. MERGE entities on natural keys (`Creator`, `Media`, `Comment`, `User`,
   `Demographic`) with `ON CREATE`/`ON MATCH` set.
7. Create `Signal`/`Score` for this `run_id`; MERGE `HAS_SIGNAL`/`CONTRIBUTED_TO`/
   `HAS_MEDIA`/`HAS_COMMENT`/`FROM_USER` edges; association edges only if loaded.
8. Write `07-load-manifest.json` (atomic `*.tmp` → `os.replace`), schema-validated.

All Cypher parameterized; batched via `UNWIND $rows`.

**Exit:** `--stage 7` on a handle with `06-dossier.json` populates the graph and
writes a schema-valid manifest (A1).

---

### Track E — Read/audit queries (depends on B)

Write `pipeline/graph/queries.py` — parameterized helpers returning plain dicts:
- `explain_score(session, user_id, score_type, run_id)` → AQ1 (Art. 22)
- `audience_overlap(session, user_id)` → AQ2 (empty until v2)
- `art9_signals(session, user_id, run_id)` → AQ3
- `undisclosed_sponsored(session, user_id)` → AQ4

Optional thin CLI: `tools/audit.py --handle <h> --query explain_score`.

**Exit:** AQ1 returns the full signal chain (weight, value, source, confidence,
method) for a `brand_fit` score (A3); AQ3 returns Art. 9-flagged signals (A4).

---

### Track F — CLI wiring + tests (depends on D, E)

- Extend `profile_analyst.py`: `--stage 7` (and include 7 in `all`); `load`
  subcommand; honor `--allow-noncompliant`.
- Tests (`tests/graph/`):
  - `test_mappers.py` — pure mapping (no DB).
  - `test_stage7_load.py` — idempotency (A2), versioning/supersede (A7),
    deferred associations (A6), compliance gate (A5). Use a Neo4j test instance
    (testcontainers or a `--integration` marker) and skip when unavailable.
  - `test_queries.py` — AQ1/AQ3 (A3, A4).
  - `test_manifest_schema.py` — manifest validates (A1, A8).

**Exit:** `make test` green; A1–A8 pass; `make load HANDLE=sample_creator` completes
end-to-end against a local Neo4j.

---

**Dependency graph:** A → B, C → D → F; B → E → F.

## Risks

- **Neo4j availability in CI.** Stage 7 needs a live Neo4j.
  *Mitigation:* mappers are pure and unit-tested without a DB; DB-backed tests use
  testcontainers or an `--integration` marker and skip when no instance is present.
- **Cross-handle node coupling.** Shared `User`/`Demographic` nodes merge across
  handles (OQ3). *Mitigation:* default to shared merge (enables overlap); document;
  erasure of one handle must not orphan another's data — covered in spec 0004/erasure
  follow-up.
- **GDPR erasure in-graph.** 0001's `erase_profile` only deletes JSON.
  *Mitigation:* note as follow-up — a graph erasure path (`DETACH DELETE` the
  creator subgraph) should accompany this spec before any real-person data is loaded.
- **Supersede vs history (OQ1).** Hard delete loses in-graph history; JSON artifacts
  retain per-run history on disk. *Mitigation:* default hard delete; revisit if
  in-graph history is required.

## Open implementation questions

- **OQ1** Hard delete vs soft supersede of prior-run Signal/Score. *Default:* hard delete.
- **OQ2** Load all comments/users or sample. *Default:* load all present in artifacts;
  large-scale comment ingestion deferred to bot-scoring spec 0004.
- **OQ3** Cross-handle merge of shared `User`/`Demographic`. *Default:* shared merge.
