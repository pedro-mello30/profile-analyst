# Plan 0012 — Audience-Overlap Graph (Stage 5, v2a)

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
Realizes the deferred Stage 5 (association graph) designed in spec 0001 §7, the same way spec 0011
realized 0001 §6's Stage 4. Net-new code is confined to `pipeline/associations/`,
`pipeline/stage5_associations.py`, one new schema, and small edits to `models.py`,
`stage6_dossier.py`, `profile_analyst.py`, `tools/validate.py`, and `pyproject.toml`.
**No Neo4j, no GDS, no network, no cloud egress** — the graph is built in-process with `networkx`.

## Architecture (reference)

```
projects/*/02-normalized.json ──┐  (cohort: glob, deterministic sort, >=2 guard)
projects/*/03-features.json ─────┤
                                 ▼
            pipeline/stage5_associations.run(handle, project_dir)
                                 │
        ┌────────────┬───────────┼────────────┬───────────────┐
        ▼            ▼           ▼             ▼               ▼
    cohort.py     edges.py    graph.py       ego.py         gate.py
   (>=2 guard)  (content_     (networkx:    (ego subview:  (Art.9 community
                similar +     Leiden /       community,     scan + Art.22
                collaborated  Louvain +      centrality,    signals
                edge lists)   3 centralities) top-N nbrs)   enforcement)
        └────────────┴───────────┴────────────┴───────────────┘
                                 │  schema-validate (05-graph.schema.json)
                                 ▼  atomic write
                      projects/<handle>/05-graph.json   (only artifact)
                                 │
                                 ▼  (rebuild graph, re-apply Art.9 gate)
                  stage6_dossier.run → dossier.associations block
```

## Tracks

- **Track A — Contract & models.** `05-graph.schema.json`; register in `tools/validate.py`;
  `AssociationGraph` / `AssociationNeighbor` / `CommunitySummary` Pydantic models + round-trip tests.
- **Track B — Cohort discovery + `[associations]` extra.** `cohort.py` (glob, sort, `≥2` guard);
  `pyproject.toml` `[associations]` extra (`leidenalg`, `igraph`; `scikit-learn` optional).
- **Track C — Edges (depends on A).** `edges.py`: content_similar (Jaccard; optional TF-IDF) and
  collaborated families, each emitting weighted edges with `signals[]`.
- **Track D — Graph + algorithms (depends on B+C).** `graph.py`: `networkx` build; Leiden with
  Louvain fallback; degree / PageRank / betweenness; deterministic node ordering.
- **Track E — Ego view + gate (depends on A+D).** `ego.py` (top-N neighbors, communities_summary);
  `gate.py` (Art. 9 community scan, Art. 22 signals enforcement).
- **Track F — Orchestration + CLI + Stage 6 (integrates all).** `stage5_associations.run`;
  `STAGE_MAP` wiring with `--stage all` unchanged; Stage 6 surfacing + redaction.

Tracks A and B can be done in parallel. C depends on A; D depends on B+C; E depends on A+D; F
integrates all.

## Sequencing & PR boundaries

1. **PR-1 (A):** schema + models + `make validate` green. No behavior change yet.
2. **PR-2 (B):** cohort discovery + extra. Unit-tested in isolation against fixtures.
3. **PR-3 (C):** edge families. Pure functions, synthetic-cohort tests.
4. **PR-4 (D):** graph build + Leiden/Louvain + centrality. Fallback path tested with import block.
5. **PR-5 (E):** ego view + compliance gate.
6. **PR-6 (F):** orchestrator + CLI + Stage 6 surfacing + end-to-end fixture test. Flips the dossier
   `associations` block from the deferred placeholder to the ego view.

## Risks & mitigations

- **`leidenalg`/`igraph` build friction (C-extensions).** → keep behind the `[associations]` extra;
  Louvain fallback keeps the base install working and the unit suite green without the extra.
- **Cohort drift / empty cohort.** → `≥2` guard raises a typed validation error (exit 1), distinct
  from operational failures.
- **Determinism of community detection.** → seed Leiden/Louvain; sort the cohort by handle before
  construction; assert byte-identical re-runs in tests.
- **Art. 9 leakage through community membership.** → scan + redact at both Stage 5 and Stage 6
  (defense-in-depth), reusing the existing `Art9Scanner` and Stage 6 redaction path.
- **Scope creep toward true audience overlap.** → explicitly deferred to v2b in spec §9 / D9; v2a
  ships only the two `computed` edge families.

## Out of scope (this plan)

Neo4j/GDS of any kind, follower-set audience overlap, embedding-based similarity, de-duplicated reach
with CIs, graph-store writeback, and lookalike discovery beyond the on-disk cohort — all v2b+
(spec §9).
