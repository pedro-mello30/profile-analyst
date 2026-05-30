# Tasks 0002 — Neo4j Graph Persistence

Derived from `plan.md`. Tasks are grouped by track and dependency-ordered.
Checkboxes track implementation progress. Each task names its acceptance link (A1–A8).

## Track A — Schema, config, driver plumbing

- [x] **A-1** Write `schemas/07-graph-load.schema.json` (draft-7): required `run_id`,
  `handle`, `loaded_at`, `neo4j_database`, `counts.nodes`, `counts.relationships`,
  `associations` (`loaded`|`deferred`), `superseded`. → A8
- [x] **A-2** Extend `tools/validate.py` to validate the new schema in `make validate`. → A1, A8
- [x] **A-3** Add `neo4j` driver to `pyproject.toml` dependencies.
- [x] **A-4** Add env config (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
  `NEO4J_DATABASE`) and document in CLAUDE.md / `.env` example.
- [x] **A-5** Add `make load HANDLE=<handle>` target.

## Track B — Graph connection + constraints

- [x] **B-1** Write `pipeline/graph/__init__.py`.
- [x] **B-2** Write `pipeline/graph/connection.py` — `GraphSession` context manager
  wrapping the official driver with `execute_write`/`execute_read` helpers.
- [x] **B-3** Write `pipeline/graph/constraints.py` — `ensure_constraints(session)`
  with the `IF NOT EXISTS` constraint/index set from spec §5.3. Idempotent.

## Track C — Mappers (pure, unit-testable)

- [x] **C-1** `pipeline/graph/mappers.py`: `creator_from_normalized` (incl. governance).
- [x] **C-2** `media_from_normalized`, `comments_from_media`, `users_from_comments`.
- [x] **C-3** `signals_from_features(doc, run_id)` carrying `confidence`, `method`,
  `art9_risk`, `source`, `computed_at`. → A4
- [x] **C-4** `scores_from_dossier(doc, run_id)` + `contributions(...)` building
  `CONTRIBUTED_TO {weight}` edges from each score's `signals[]`. → A3
- [x] **C-5** `associations_from_graph(doc)` → `(edges, "loaded")` or
  `([], "deferred")` when `05-graph.json` is absent. → A6

## Track D — Stage 7 LOAD orchestrator

- [x] **D-1** `pipeline/stage7_load.py` skeleton: resolve `run_id` + `loaded_at`,
  load artifacts `02`/`03`/`05?`/`06`.
- [x] **D-2** Compliance gate: `assert_governance_complete` on creator props; honor
  `--allow-noncompliant`. → A5
- [x] **D-3** Call `ensure_constraints(session)` at load start.
- [x] **D-4** Supersede prior-run `Signal`/`Score` for the creator
  (`DETACH DELETE` where `run_id <> $run_id`). → A7
- [x] **D-5** MERGE entities on natural keys with `ON CREATE`/`ON MATCH SET`
  (batched via `UNWIND`). → A1, A2
- [x] **D-6** Create `Signal`/`Score` (this `run_id`) + MERGE all edges; association
  edges only when loaded. → A3, A6
- [x] **D-7** Write `07-load-manifest.json` atomically; schema-validate. → A1, A8

## Track E — Read/audit queries

- [x] **E-1** `pipeline/graph/queries.py`: `explain_score` (AQ1, Art. 22). → A3
- [x] **E-2** `audience_overlap` (AQ2; empty until v2).
- [x] **E-3** `art9_signals` (AQ3). → A4
- [x] **E-4** `undisclosed_sponsored` (AQ4).
- [x] **E-5** Optional `tools/audit.py` CLI wrapper for the queries.

## Track F — CLI wiring + tests

- [x] **F-1** Extend `profile_analyst.py`: `--stage 7`, include 7 in `all`, `load`
  subcommand, `--allow-noncompliant`.
- [x] **F-2** `tests/graph/test_mappers.py` — pure mapping, no DB.
- [x] **F-3** `tests/graph/test_stage7_load.py` — idempotency (A2), versioning (A7),
  deferred associations (A6), compliance gate (A5). Skip when no Neo4j.
- [x] **F-4** `tests/graph/test_queries.py` — AQ1 (A3), AQ3 (A4).
- [x] **F-5** `tests/graph/test_manifest_schema.py` — manifest validates (A1, A8).
- [x] **F-6** Verify `make test` green and `make load HANDLE=sample_creator` runs
  end-to-end against a local Neo4j.

## Acceptance coverage map

| Acceptance | Covered by |
|---|---|
| A1 manifest valid + nodes/edges created | A-1, A-2, D-5, D-7 |
| A2 idempotent re-run | D-5, F-3 |
| A3 Art. 22 score explanation | C-4, E-1, F-4 |
| A4 Art. 9 flags preserved | C-3, E-3, F-4 |
| A5 compliance gate | D-2, F-3 |
| A6 deferred associations | C-5, D-6, F-3 |
| A7 signal/score versioning | D-4, F-3 |
| A8 `make validate` passes | A-1, A-2, D-7, F-5 |
