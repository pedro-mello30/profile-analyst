# Plan 0004 — Neo4j GDS (Stage 9)

**Spec:** `specs/0004-neo4j-gds/spec.md`
**Status:** accepted → in implementation
**Owner:** Pedro Mello

---

## Architecture Reference

```
pipeline/
├── stage9_gds.py         # NEW — orchestrates project → run AL1–AL5 → write-back → manifest
├── graph/
│   ├── gds.py            # NEW — GDS plugin gate, projection lifecycle (project/drop, finally)
│   ├── gds_algorithms.py # NEW — AL1–AL5 runners (Louvain, degree, betweenness, similarity, linkpred)
│   ├── gds_writeback.py  # NEW — Signals, SHARES_AUDIENCE / COLLABORATED_WITH edges, fraud_risk Score
│   ├── writers.py        # 0002 — reused for MERGE/UNWIND helpers
│   └── queries.py        # 0002 — extended with GQ1–GQ3
└── ...
schemas/
└── 11-gds.schema.json    # NEW — Stage 9 GDS manifest schema
```

Stage 9 reads only the live Neo4j graph from 0002 (no JSON inputs) and runs over the **whole graph
(cross-handle)**; `--handle` scopes only which manifest/summary is written.

## Tracks

### Track A — GDS plugin gate + projection lifecycle (foundation)
**Scope:** `pipeline/graph/gds.py`. `gds.version()` capability check (fail fast, non-zero, clear
message); `gds.graph.project` over `['Creator','User','Comment','Media']` as an UNDIRECTED
co-engagement projection; `gds.graph.drop(..., false)` at start and in a `finally` block.
**Exit:** with the plugin absent, the stage exits non-zero with "Neo4j GDS plugin not installed" and
mutates nothing (A8); after any run (success or failure) the projection `GDS_GRAPH_NAME` does not
exist (A9).

### Track B — Algorithms AL1–AL5
**Scope:** `pipeline/graph/gds_algorithms.py`. Stream-mode runners for Louvain (AL1), degree (AL2),
betweenness (AL3), Node Similarity with `topK`/`cutoff` (AL4), and Adamic-Adar link prediction
(AL5), each returning typed Python results. Reads config from §9 env (cutoffs, topK, max levels).
**Depends on:** Track A (projection must exist).
**Exit:** each algorithm produces the expected per-node/per-pair results on the sample graph;
deterministic re-run yields identical values (seeded where GDS exposes a seed).

### Track C — Write-back + idempotency
**Scope:** `pipeline/graph/gds_writeback.py`. Write `community_id` / `degree_centrality` /
`betweenness_centrality` `Signal`s (`method:computed`, `source:gds`); `MERGE` `SHARES_AUDIENCE
{overlap_pct}` (above `GDS_SIMILARITY_CUTOFF`) and `COLLABORATED_WITH {predicted,probability}`
edges; compute the `fraud_risk` `Score` as the named-weight blend and link each contributing signal
via `CONTRIBUTED_TO {weight}`. `run_id` stamping + supersede prior-run GDS artifacts (default
hard-delete).
**Depends on:** Track B.
**Exit:** A1 (all artifacts written), A2 (idempotent re-run, identical counts/values), A4
(SHARES_AUDIENCE non-empty), A7 (versioning supersedes prior run).

### Track D — Stage 9 orchestration + manifest + CLI
**Scope:** `pipeline/stage9_gds.py`, `schemas/11-gds.schema.json`, CLI `--stage 9` + `--stage all`
wiring in `profile_analyst.py`, `make gds` target. Manifest records `run_id`, `gds_version`,
projection name, algorithms run, counts written, fraud blend weights, `model_version`,
`data_egress: none`.
**Depends on:** Track C.
**Exit:** `--stage 9` runs end-to-end and writes a `09-gds-manifest.json` that validates against
`schemas/11-gds.schema.json` (A1, A10).

### Track E — Compliance gates + audit queries
**Scope:** governance gate on projection membership (C1, `--allow-noncompliant`); method-honesty
enforcement (C4); Art. 9 proxy caution on `community_id` (C2); `GQ1`–`GQ3` parameterized helpers in
`pipeline/graph/queries.py`.
**Depends on:** Track C (artifacts to query/gate).
**Exit:** A3 (GQ1 full signal chain), A5 (governance gate fails closed without override), A6 (every
written Signal is `method:computed`, `source:gds`).

## Risks

- **R1.** Neo4j + GDS plugin not running locally → integration tests need a Neo4j-with-GDS container
  (testcontainers / compose with the GDS plugin image) or a graceful skip.
- **R2.** `fraud_risk` normalization is unstable on tiny fixture graphs (OQ3) → use min-max within
  the run and record the bounds in the manifest.
- **R3.** Cross-handle projection couples to 0002 OQ3 (shared `User` merging); overlap/pods are
  trivial/empty if the graph holds a single creator → seed the fixture with multiple creators sharing
  commenters.
- **R4.** GDS procedure names differ across GDS major versions (e.g. `gds.alpha.linkprediction`) →
  pin a GDS version and assert it via the `gds.version()` gate.

## Open Questions

(See spec §11 — OQ1 hard vs soft supersede, OQ2 co-engagement edge definition, OQ3 fraud_risk
normalization, OQ4 topological vs trained link prediction.)
