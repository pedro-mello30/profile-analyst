# Tasks 0012 — Audience-Overlap Graph (Stage 5, v2a)

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A and B can be done in parallel. C depends on A; D depends on B+C; E depends on A+D;
F integrates all. **No Neo4j, no GDS, no network in any task.**

---

## Track A — Contract & models

- [ ] T1 Create `schemas/05-graph.schema.json` (draft-7): top-level `handle`, `method_version`
      (enum `["v2a"]`), preserved `governance` block, `cohort_size` (int ≥2), `community_method`
      (enum `["leiden","louvain"]`).
- [ ] T2 Define `ego` (`community_id`, `community_size`, `centrality` object with required
      `degree`/`pagerank`/`betweenness`), `neighbors[]` (items `{handle, edge_type`
      (enum `content_similar|collaborated`), `weight` (number 0–1), `method`, `signals[]`
      (`minItems: 1`)}`), `communities_summary[]` (`{community_id, size, members[], art9_risk}`),
      and `warnings[]`; mark the required set and `additionalProperties: false`.
- [ ] T3 Register `05-graph.schema.json` in `tools/validate.py` so `make validate` checks it.
- [ ] T4 Add `AssociationGraph`, `AssociationNeighbor`, `CommunitySummary` Pydantic v2 models to
      `pipeline/models.py` (validators: `weight ∈ [0,1]`, `signals` non-empty, centrality keys
      present).
- [ ] T5 Unit test: `AssociationGraph` round-trips a hand-written ego view and rejects a neighbor
      with empty `signals[]` (`tests/associations/test_models.py`).

**Exit (Track A):** `make validate` green with the new schema; model round-trip + rejection tests pass.

---

## Track B — Cohort discovery + `[associations]` extra

- [ ] T6 Create `pipeline/associations/cohort.py` — `discover_cohort(projects_dir)` globs
      `projects/*/02-normalized.json`, loads each into `Profile`, sorts by handle, returns the list.
- [ ] T7 Enforce the `≥2` guard: raise a typed validation error (mapped to exit 1) when the cohort
      has fewer than two members; the seed `<handle>` is always included.
- [ ] T8 Add the `[associations]` optional extra to `pyproject.toml` (`leidenalg`, `igraph`;
      `scikit-learn` listed as the optional TF-IDF dep).
- [ ] T9 Unit test: cohort discovery over a 3-profile fixture returns a deterministic sorted list;
      a single-profile cohort raises (`tests/associations/test_cohort.py`).

**Exit (Track B):** cohort discovery deterministic; `≥2` guard tested; base install unaffected by the extra.

---

## Track C — Edge families (depends on A)

- [ ] T10 Create `pipeline/associations/edges.py` — `content_similar_edges(cohort)`: token-set
      Jaccard over niche+hashtag tokens; keep edges `≥ CONTENT_SIM_THRESHOLD (=0.60)`; emit
      `{weight, method:"computed", signals[]}` (shared tokens in `signals`).
- [ ] T11 `collaborated_edges(cohort)`: mutual @mentions / co-tags / co-sponsored brands; weight =
      normalized shared-collaboration count; `method:"computed"`; collaboration evidence in
      `signals[]`.
- [ ] T12 Optional TF-IDF cosine path (`scikit-learn`) selected only when importable; same threshold
      semantics; no-op import guard otherwise.
- [ ] T13 Unit tests: high/low/no-overlap synthetic pairs cross the Jaccard threshold as expected;
      disjoint-mention pairs yield no collaboration edge; every emitted edge has non-empty `signals`
      (`tests/associations/test_edges.py`).

**Exit (Track C):** both edge families are pure, deterministic, and signal-bearing.

---

## Track D — Graph + algorithms (depends on B+C)

- [ ] T14 Create `pipeline/associations/graph.py` — build a `networkx.Graph` from the union of edge
      families (nodes sorted by handle for determinism; `edge_type` retained on collapse).
- [ ] T15 Communities via Leiden (`leidenalg` over an `igraph` view, seeded) behind the
      `[associations]` extra; fall back to `networkx.community.louvain_communities` (seeded) when the
      import is unavailable; set `community_method` accordingly.
- [ ] T16 Centrality: `degree_centrality`, `pagerank`, `betweenness_centrality` (native `networkx`),
      annotated onto nodes.
- [ ] T17 Unit tests: two-cluster graph yields two communities; star/bridge topology orders
      centralities as expected; with `leidenalg` import-blocked the Louvain fallback runs and records
      `community_method='louvain'` (`tests/associations/test_graph.py`).

**Exit (Track D):** communities + 3 centralities computed deterministically; fallback path proven.

---

## Track E — Ego view + compliance gate (depends on A+D)

- [ ] T18 Create `pipeline/associations/ego.py` — select the seed node; read community + centrality;
      rank incident edges by weight → `neighbors[]` (`EGO_TOP_N=10`); roll up `communities_summary[]`.
- [ ] T19 Create `pipeline/associations/gate.py` — run `Art9Scanner` over each community's aggregate
      niche/hashtag evidence → `art9_risk`; assert every neighbor edge has a non-empty `signals[]`
      (raise otherwise).
- [ ] T20 Unit tests: ego view picks the correct top-N by weight; an Art.9-tripping community is
      flagged; the gate raises on a signal-less edge (`tests/associations/test_ego_gate.py`).

**Exit (Track E):** ego view correct; Art. 9 flag set; Art. 22 signals enforced.

---

## Track F — Orchestration + CLI + Stage 6 (integrates all)

- [ ] T21 Create `pipeline/stage5_associations.py` — `run(handle, project_dir)`: cohort → edges →
      graph → ego → gate → schema-validate → atomic write `05-graph.json`. Idempotent; no other
      artifact touched.
- [ ] T22 Wire `profile_analyst.py`: `STAGE_MAP` gains `5 → stage5_associations.run`; confirm
      `--stage all` expansion stays `1,2,3,6,7,8,9`; `--stage 5` runs only associations.
- [ ] T23 Stage 6 surfacing in `pipeline/stage6_dossier.py`: when `05-graph.json` exists, fill the
      `associations` block with the ego view, re-run the Art.9 community gate (defense-in-depth) and
      redact flagged member lists absent consent; keep `{"status":"deferred","graph_summary":null}`
      when the artifact is absent.
- [ ] T24 End-to-end test over a committed `≥2`-profile fixture: `--stage 5` writes a schema-valid
      `05-graph.json`; Stage 6 surfaces the ego view; an absent artifact keeps the placeholder; two
      runs produce a byte-identical artifact (`tests/associations/test_stage5_e2e.py`,
      `tests/test_stage6_associations.py`).
- [ ] T25 `_parse_stages` test: `all` excludes 5; `5` includes it (alongside existing stage-parsing
      tests).

**Exit (Track F):** `make validate` + offline unit suite green; dossier `associations` block flips
from the deferred placeholder to the ego view; no network, no database touched.
