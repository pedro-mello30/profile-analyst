# Spec 0004 — Neo4j GDS (Graph Data Science)

**Status:** draft
**Depends on:** `0002-neo4j-graph-persistence` (runs over the graph it loads) ·
`0001-social-media-associations-profile` (preserves its invariants on written-back nodes)
**Owner:** Pedro Mello
**Created:** 2026-05-30

---

## 1. Problem Statement

Spec 0002 loads the creator dossier into Neo4j and ships static Cypher audit queries, but it
explicitly defers all graph **data-science algorithms** (its N1, future-work item "Spec 0004"). The
headline influencer-marketing analytics named in 0002 §1 are inherently algorithmic and cannot be
answered by traversal alone:

- **Engagement-pod / fraud-ring detection** — the same tight cluster of accounts commenting on every
  post is a *community-structure* problem (Louvain / modularity).
- **Bot detection** — accounts with anomalous connectivity are a *centrality* problem
  (degree + betweenness).
- **Audience overlap / duplicate reach** — creators sharing the same commenters/audience is a
  *node-similarity* problem; its results are exactly the `SHARES_AUDIENCE {overlap_pct}` edges that
  0002 §5.2 left deferred `[v2]`.
- **Likely (undeclared) collaborations** — a *link-prediction* problem over the co-engagement graph.

This spec adds the **Neo4j GDS plugin** and a new idempotent **Stage 9 GDS** that projects the 0002
graph in memory, runs these algorithms over the **whole graph (cross-handle)**, and writes the
results **back into the property graph** as `Signal`/`Score` nodes and the previously-deferred
`SHARES_AUDIENCE` / `COLLABORATED_WITH` edges — preserving every 0001/0002 invariant
(`confidence`, `method`, `art9_risk`, `signals[]` explainability, governance gate). Downstream, 0005
RAG consumes these signals when present (its `relates_to: 0004-neo4j-gds`).

## 2. Goals

- G1. Add the **Neo4j GDS plugin** and a dedicated, idempotent **Stage 9 GDS** that runs over the
  loaded graph and writes results back as graph nodes/edges + a `09-gds-manifest.json`.
- G2. Deliver the **full algorithm set**: Louvain (communities/pods), degree + betweenness centrality
  (bot signal), Node Similarity (audience overlap), and link prediction (likely collaborations).
- G3. Materialize the **0002-deferred edges** `SHARES_AUDIENCE {overlap_pct}` (from Node Similarity)
  and `COLLABORATED_WITH {predicted, probability}` (from link prediction).
- G4. Derive a **`fraud_risk` `Score`** from the algorithmic signals, carrying its full `signals[]`
  explainability chain (`CONTRIBUTED_TO {weight}`) for GDPR Art. 22.
- G5. Preserve every invariant: each written `Signal` carries `confidence`, `method: computed`,
  `art9_risk`; each `Score` carries `signals[]`; governance-failed creators are excluded.
- G6. **Idempotent + versioned** like Stage 7: each run gets a `run_id`; prior-run GDS signals/scores
  for the graph are superseded; the in-memory projection is dropped and rebuilt each run.

## 3. Non-Goals

- N1. **No changes to Stage 7 LOAD or its artifacts.** Stage 9 reads the graph 0002 wrote and adds to
  it; it never re-runs the load or edits `02/03/05/06` JSON.
- N2. **No new database or relational store** (0002 N2 spirit). GDS uses Neo4j's in-memory graph
  catalog; nothing leaves Neo4j.
- N3. **No supervised ML training / GDS ML pipelines** in v1. Link prediction uses GDS topological
  link-prediction functions (Adamic-Adar / common-neighbors style), not a trained model.
- N4. **No live Instagram data source.** The 0001 SampleAdapter still seeds the graph.
- N5. **No write-back into the dossier JSON.** Results live in Neo4j only (mirrors 0002 N5).
- N6. **No GDPR erasure automation** (still a cross-cutting follow-up flagged in 0002 future-work).

## 4. Pipeline Integration

```
Stage 7  LOAD   → Neo4j graph + 07-load-manifest.json        (from spec 0002)
Stage 8  EMBED  → embeddings on Creator/Media                 (from spec 0005, independent)
Stage 9  GDS    → graph signals/edges + 09-gds-manifest.json  (THIS SPEC)
```

- New module `pipeline/stage9_gds.py`.
- CLI: `python3 profile_analyst.py --handle <handle> --stage 9` (and `--stage all` runs 1–9).
  Because GDS is cross-handle, `--handle` scopes only *which creator's* manifest/summary is written;
  the algorithms run over the whole graph (see §6).
- New `make` target: `make gds [HANDLE=<handle>]`.
- Access via the official `neo4j` Python driver + the **GDS Cypher procedures** (`gds.*`),
  parameterized, with explicit write transactions for the write-back phase.
- Stage 9 requires the **GDS plugin**; if absent it exits non-zero with a clear message (§9, A8).
- Stage 9 emits `projects/<handle>/09-gds-manifest.json` validated against
  `schemas/11-gds.schema.json`.

### 4.1 Inputs

Stage 9 reads **only the live Neo4j graph** from 0002 (no JSON inputs):
- `Creator`, `Comment`, `User`, `Media` nodes and the `HAS_MEDIA / HAS_COMMENT / FROM_USER` edges
  define the co-engagement structure the algorithms run over.
- Governance metadata on `Creator` gates inclusion (C1, mirrors 0005 C5).

## 5. Algorithms & Write-Back

All algorithms run on a **native in-memory projection** (`gds.graph.project`, §6). Each produces
graph artifacts and a manifest entry. `method` is always `computed`; `art9_risk` defaults `false`
(see C2 for the proxy caveat).

| # | Algorithm | GDS proc | Produces | Written back as |
|---|-----------|----------|----------|-----------------|
| AL1 | **Louvain** | `gds.louvain.write` / `.stream` | community id + modularity per Creator | `Signal {name:"community_id"}`; `Creator.community_id` |
| AL2 | **Degree centrality** | `gds.degree.stream` | in/out degree per node | `Signal {name:"degree_centrality"}` |
| AL3 | **Betweenness centrality** | `gds.betweenness.stream` | brokerage score per Creator | `Signal {name:"betweenness_centrality"}` |
| AL4 | **Node Similarity** | `gds.nodeSimilarity.stream` | Jaccard overlap of shared audience | `(:Creator)-[:SHARES_AUDIENCE {overlap_pct}]->(:Creator)` |
| AL5 | **Link prediction** | `gds.alpha.linkprediction.*` (Adamic-Adar) | likely missing co-engagement links | `(:Creator)-[:COLLABORATED_WITH {predicted:true, probability}]->(:Creator)` |

### 5.1 Derived `fraud_risk` Score (G4)

A `fraud_risk` `Score` is computed per Creator from the algorithmic signals as a **documented,
named-weight linear blend** (weights are constants, parameterizable in tests, recorded in the
manifest — per the 0001 convention):

```
fraud_risk = w_pod * pod_density_norm        # tight small Louvain community (engagement pod)
           + w_btw * betweenness_norm         # anomalous brokerage (ring hub)
           + w_deg * degree_zscore_norm       # anomalous degree (bot-like)
```

Each contributing signal is linked `(:Creator)-[:CONTRIBUTED_TO {weight}]->(:Score {type:"fraud_risk"})`
so AQ-style queries reconstruct the full chain (Art. 22). The `Score` carries `model_version`
(e.g. `gds-fraud-v1`), `run_id`, `created_at`, `status:"active"`.

### 5.2 Edges materialized (fills 0002 deferred `[v2]`)

```cypher
// AL4 → audience overlap (only pairs above GDS_SIMILARITY_CUTOFF)
MATCH (a:Creator {user_id:$a}), (b:Creator {user_id:$b})
MERGE (a)-[r:SHARES_AUDIENCE]->(b)
  SET r.overlap_pct = $jaccard, r.run_id = $run_id, r.method = 'computed'

// AL5 → predicted collaboration
MATCH (a:Creator {user_id:$a}), (b:Creator {user_id:$b})
MERGE (a)-[r:COLLABORATED_WITH]->(b)
  SET r.predicted = true, r.probability = $p, r.run_id = $run_id
```

0002's `AQ2` (audience overlap) returns rows once Stage 9 has run; 0005 OQ3 (centrality-weighted
graph-leg ranking) is satisfied by the `betweenness_centrality` / `community_id` signals.

## 6. Projection, Idempotency & Versioning (mirrors 0002 §6)

- **Projection.** Each run drops and recreates a named projection so it reflects the current graph:

```cypher
CALL gds.graph.drop($graph_name, false) YIELD graphName;     // false = don't error if missing
CALL gds.graph.project(
  $graph_name,
  ['Creator','User','Comment','Media'],
  { ENGAGES: { type: '*', orientation: 'UNDIRECTED' } }      // co-engagement projection
);
```

- **Run identity.** Each Stage 9 run gets a `run_id` (UUID), stamped on every written Signal/Score
  and on the new edges.
- **Supersede prior run.** At the start, prior GDS-authored signals/scores/edges are superseded
  (detach-deleted by default; soft-supersede is OQ1, consistent with 0002 OQ1):

```cypher
MATCH (c:Creator)-[:HAS_SIGNAL]->(s:Signal {source:'gds'})
WHERE s.run_id <> $run_id
DETACH DELETE s;
MATCH ()-[r:SHARES_AUDIENCE|COLLABORATED_WITH]-() WHERE r.run_id <> $run_id DELETE r;
```

- **Idempotency guarantee (A2).** Running `--stage 9` twice over an unchanged graph yields identical
  node/edge counts and identical signal/score values (deterministic algorithms; seeded where GDS
  exposes a seed).
- **Cleanup.** The in-memory projection is dropped at the end of every run (success or failure).

## 7. Compliance Invariants (carried from 0001 §9 / 0002 §7)

- C1. **Governance gate.** Only `Creator`s that passed the 0002 governance gate are included in the
  projection. A creator missing `gdpr_basis` / `subject_jurisdiction` / `tos_compliant_at_ingest` is
  excluded unless `--allow-noncompliant` is passed (mirrors Stage 1/7).
- C2. **Art. 9 proxy caution.** GDS structural signals are `art9_risk:false` by default, BUT a
  `community_id` MUST NOT be used as a proxy for a protected attribute. The manifest records a
  `art9_proxy_warning` note; if any community correlates with an existing `art9_risk` signal cluster,
  that community's `Signal` is flagged `art9_risk:true`.
- C3. **Art. 22 explainability.** `fraud_risk` is a decision-affecting score → every contributing
  signal is linked via `CONTRIBUTED_TO {weight}`; the blend weights + `model_version` are in the
  manifest. Human-review path and opt-out are inherited from 0001 §9 (the score is advisory).
- C4. **Method honesty.** All written signals carry `method:"computed"` and `source:"gds"` — never
  `inferred`/`llm` — so audits can distinguish algorithmic from model-derived signals.
- C5. **No data egress.** GDS runs entirely inside Neo4j; the manifest records
  `data_egress: none`.

## 8. Read / Audit Queries (delivered)

**GQ1 — Top fraud-risk creators with their signal chain (Art. 22):**

```cypher
MATCH (c:Creator)-[r:CONTRIBUTED_TO]->(s:Score {type:'fraud_risk', run_id:$run_id})
MATCH (c)-[hs:HAS_SIGNAL]->(sig:Signal {source:'gds', run_id:$run_id})
RETURN c.username, s.value AS fraud_risk,
       collect({signal:sig.name, weight:hs.weight, value:sig.value}) AS signals
ORDER BY fraud_risk DESC LIMIT 20
```

**GQ2 — Engagement pods (small, dense Louvain communities):**

```cypher
MATCH (c:Creator)-[:HAS_SIGNAL]->(s:Signal {name:'community_id', run_id:$run_id})
WITH s.value AS community, collect(c.username) AS members
WHERE size(members) > 1 AND size(members) <= $pod_max
RETURN community, members ORDER BY size(members) DESC
```

**GQ3 — Audience overlap (now populated; 0002 AQ2 parity):**

```cypher
MATCH (a:Creator)-[r:SHARES_AUDIENCE {run_id:$run_id}]->(b:Creator)
RETURN a.username, b.username, r.overlap_pct ORDER BY r.overlap_pct DESC
```

These ship as parameterized helpers alongside 0002's audit queries (e.g. `pipeline/queries.py`).

## 9. Configuration

```
# all 0002 Neo4j config (NEO4J_URI/USER/PASSWORD/DATABASE) plus:
GDS_GRAPH_NAME=profile-analyst        # in-memory projection name
GDS_SIMILARITY_CUTOFF=0.10            # min Jaccard to write a SHARES_AUDIENCE edge
GDS_TOPK_SIMILARITY=10                # Node Similarity topK per node
GDS_LINKPRED_TOPN=10                  # predicted links kept per node
GDS_LOUVAIN_MAX_LEVELS=10
GDS_FRAUD_WEIGHTS=pod:0.5,btw:0.3,deg:0.2   # fraud_risk blend (recorded in manifest)
GDS_POD_MAX=8                         # max community size still considered a "pod"
ALLOW_NONCOMPLIANT=false              # mirrors Stage 1/7 governance gate
```

Local dev requires **Neo4j 5.x with the GDS plugin** (Community edition + GDS is sufficient for these
algorithms). If the plugin is missing, `gds.version()` fails fast (A8).

## 10. Acceptance Criteria

- A1. `--stage 9` over a 0002-loaded graph runs AL1–AL5, writes `community_id` / `degree_centrality`
  / `betweenness_centrality` Signals, `SHARES_AUDIENCE` + `COLLABORATED_WITH` edges, and a
  `fraud_risk` Score; `09-gds-manifest.json` validates against `schemas/11-gds.schema.json`.
- A2. **Idempotency:** running `--stage 9` twice over an unchanged graph yields identical node/edge
  counts and identical signal/score values (no duplicates).
- A3. **Art. 22:** GQ1 returns each top fraud-risk creator with its full contributing-signal chain
  (name, weight, value); the blend weights + `model_version` appear in the manifest.
- A4. **Edges materialized:** after Stage 9, 0002's AQ2 / this spec's GQ3 return non-empty
  `SHARES_AUDIENCE` rows for creators above `GDS_SIMILARITY_CUTOFF`.
- A5. **Governance gate:** a creator missing governance metadata is excluded from the projection
  without `--allow-noncompliant` and included with it.
- A6. **Method honesty:** every GDS-written Signal carries `method:"computed"`, `source:"gds"`; none
  are `inferred`/`llm`.
- A7. **Versioning:** a second run supersedes the prior run's GDS signals/scores/edges; GQ1 with the
  new `run_id` reflects the new values and the old `run_id` artifacts are gone (default hard-delete).
- A8. **Plugin gate:** with the GDS plugin absent, `--stage 9` exits non-zero with a clear
  "Neo4j GDS plugin not installed" message and writes no partial graph mutations.
- A9. **Projection hygiene:** the in-memory projection named `GDS_GRAPH_NAME` does not exist after a
  run completes or fails (dropped in a finally block).
- A10. `make validate` passes with the new `schemas/11-gds.schema.json`.

## 11. Open Questions

- OQ1. **Hard delete vs soft supersede** of prior-run GDS signals/scores/edges (default: hard delete,
  consistent with 0002 OQ1; the JSON dossier is unaffected either way).
- OQ2. **Co-engagement edge definition** for the projection: shared-commenter (User→Comment→Media→
  Creator) only, or also follow/collab edges if later added? (default: shared-commenter via the
  existing 0002 model.)
- OQ3. **fraud_risk normalization** across a small fixture graph: z-score vs min-max — z-score is
  unstable on tiny graphs (default: min-max within the run, recorded in manifest).
- OQ4. **Link-prediction without ground truth:** topological (Adamic-Adar) only in v1; a trained GDS
  ML pipeline is future work (N3).

## 12. Future Work (out of scope here)

- Trained GDS ML link-prediction pipeline (replacing the topological heuristic in AL5).
- Graph-side GDPR erasure path (`DETACH DELETE` creator subgraph + projection invalidation).
- Feeding GDS signals into 0005 RAG as explicit RRF weights / rerank features (0005 future-work).
- Temporal GDS (community drift / centrality trend across `run_id`s) for longitudinal fraud signals.
- Neo4j Bloom dashboards visualizing pods and audience-overlap clusters for brand teams.
