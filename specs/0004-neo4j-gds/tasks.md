# Tasks 0004 — Neo4j GDS (Stage 9)

**Spec:** `specs/0004-neo4j-gds/spec.md`
**Plan:** `specs/0004-neo4j-gds/plan.md`

---

## Track A — GDS plugin gate + projection lifecycle

- [ ] T1. `pipeline/graph/gds.py`: `gds.version()` capability gate — fail fast, non-zero, clear "Neo4j GDS plugin not installed" message (A8).
- [ ] T2. Projection lifecycle: `gds.graph.project` (Creator/User/Comment/Media, UNDIRECTED) + `gds.graph.drop(..., false)` at start.
- [ ] T3. `finally`-block drop so the projection never outlives a run, even on failure (A9).
- [ ] T4. Unit test: plugin-absent path mutates nothing; projection gone after success and after failure.

## Track B — Algorithms AL1–AL5

- [ ] T5. `pipeline/graph/gds_algorithms.py`: Louvain (AL1) with `GDS_LOUVAIN_MAX_LEVELS`.
- [ ] T6. Degree (AL2) + betweenness (AL3) centrality runners.
- [ ] T7. Node Similarity (AL4) with `GDS_TOPK_SIMILARITY` + `GDS_SIMILARITY_CUTOFF`.
- [ ] T8. Adamic-Adar link prediction (AL5) with `GDS_LINKPRED_TOPN`.
- [ ] T9. Unit test: deterministic re-run yields identical values (seeded where exposed).

## Track C — Write-back + idempotency

- [ ] T10. `pipeline/graph/gds_writeback.py`: write `community_id` / `degree_centrality` / `betweenness_centrality` Signals (`method:computed`, `source:gds`).
- [ ] T11. `MERGE` `SHARES_AUDIENCE {overlap_pct}` edges above `GDS_SIMILARITY_CUTOFF` (fills 0002 [v2]).
- [ ] T12. `MERGE` `COLLABORATED_WITH {predicted,probability}` edges from AL5.
- [ ] T13. Compute `fraud_risk` Score (named-weight blend, `GDS_FRAUD_WEIGHTS`) + `CONTRIBUTED_TO {weight}` chain.
- [ ] T14. `run_id` stamping + supersede prior-run GDS artifacts (default hard-delete).
- [ ] T15. Unit test: idempotent re-run yields identical counts/values (A2); second run supersedes prior (A7).

## Track D — Stage 9 orchestration + manifest + CLI

- [ ] T16. `pipeline/stage9_gds.py`: orchestrate project → AL1–AL5 → write-back → manifest.
- [ ] T17. `schemas/11-gds.schema.json`: manifest schema (run_id, gds_version, algorithms, counts, blend weights, model_version, data_egress).
- [ ] T18. CLI `--stage 9` + `--stage all` wiring in `profile_analyst.py`; `make gds` target.
- [ ] T19. Integration test: end-to-end `--stage 9` manifest is schema-valid (A1, A10).

## Track E — Compliance gates + audit queries

- [ ] T20. Governance gate on projection membership; `--allow-noncompliant` override (C1, A5).
- [ ] T21. Method-honesty assertion: every written Signal is `method:computed`, `source:gds` (C4, A6).
- [ ] T22. Art. 9 proxy caution: `art9_proxy_warning` in manifest; flag `community_id` Signal `art9_risk:true` when it correlates with an art9 cluster (C2).
- [ ] T23. `pipeline/graph/queries.py`: `GQ1`–`GQ3` parameterized helpers (spec §8).
- [ ] T24. Compliance test: missing-governance creator excluded without override (A5); GQ1 returns full signal chain (A3).

## Validation

- [ ] T25. `make validate` green.
- [ ] T26. `make test` green.
- [ ] T27. Update CLAUDE.md (stage list, `--stage 9`, `make gds`, `GDS_*` env, gds plugin requirement) if changed.
