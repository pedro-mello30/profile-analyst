# Spec 0002 — Neo4j Graph Persistence

**Status:** draft
**Depends on:** `0001-social-media-associations-profile` (consumes its stage artifacts)
**Owner:** Pedro Mello
**Created:** 2026-05-30

---

## 1. Problem Statement

Pipeline 0001 produces a JSON dossier (`projects/<handle>/06-dossier.json` + `report.md`) but
has no graph store. The core analytics use cases for influencer marketing are inherently
graph/traversal problems that flat JSON cannot serve:

- **Engagement-pod / fraud-ring detection** — the same small set of accounts commenting on every
  post (community structure).
- **Bot detection** — accounts with anomalous in/out-degree (centrality).
- **Audience overlap / duplicate reach** — creators sharing the same audience.
- **GDPR Art. 22 "right to explanation"** — given a score, return the exact signal chain that
  produced it, on demand, as an audit trail.

This spec adds **Neo4j as the primary graph store** and a new idempotent **Stage 7 LOAD** that
upserts the dossier's entities, signals, and scores into the graph. The existing JSON artifacts
are retained unchanged as the document/audit/replay store.

## 2. Goals

- G1. Persist the pipeline output into Neo4j with a stable, queryable graph model.
- G2. A dedicated, idempotent **Stage 7 LOAD** reads existing JSON artifacts (02, 03, 05, 06) and
  upserts the graph. Re-running for the same handle creates **no duplicate** nodes or edges.
- G3. Preserve every 0001 invariant in the graph: governance metadata, `confidence`/`method`
  on features, `art9_risk` flags, and the `signals[]` explainability chain on every score.
- G4. Provide **Cypher audit/read queries** that satisfy GDPR Art. 22 (score explanation) and
  surface audience overlap — without losing historical score versions.

## 3. Non-Goals

- N1. **No graph data-science algorithms** (Louvain community detection, centrality, link
  prediction). These require the Neo4j GDS plugin and are **deferred to spec 0004**.
- N2. **No new relational/document database.** Postgres/MongoDB are explicitly out of scope; the
  existing `projects/<handle>/*.json` files remain the document/audit store.
- N3. No changes to 0001's stages 1–6 behavior or artifacts. Stage 7 only reads them.
- N4. No live Instagram data source (the SampleAdapter from 0001 still seeds the data).
- N5. No graph-write path back into the dossier JSON (load is one-directional: JSON → Neo4j).

## 4. Pipeline Integration

```
Stage 6  DOSSIER   → 06-dossier.json + report.md          (from spec 0001)
Stage 7  LOAD      → Neo4j graph + 07-load-manifest.json   (THIS SPEC)
```

- New module `pipeline/stage7_load.py`.
- CLI: `python3 profile_analyst.py --handle <handle> --stage 7`
  (and `--stage all` runs 1–7).
- New `make` target: `make load HANDLE=<handle>`.
- Access via the **official `neo4j` Python driver**, parameterized Cypher, explicit
  write transactions. Added to the stack/deps.
- Stage 7 emits `07-load-manifest.json` (counts of nodes/edges merged, `run_id`, `loaded_at`)
  validated against `schemas/07-graph-load.schema.json`.

### 4.1 Inputs

Stage 7 reads, in order, whichever exist:
- `02-normalized.json` — canonical `Profile` + governance metadata → `Creator`, `Media`, `User`,
  `Comment` nodes.
- `03-features.json` — feature catalog → `Signal` nodes (+ `art9_risk`, `confidence`, `method`).
- `05-graph.json` — overlap/associations `[v2]` → `SHARES_AUDIENCE`, `COLLABORATED_WITH`,
  `HAS_AUDIENCE_SEGMENT` edges. **Absent in v1 → loaded as `status: deferred` placeholder.**
- `06-dossier.json` — scores → `Score` nodes with `signals[]` provenance.

## 5. Graph Data Model

### 5.1 Nodes

| Label | Natural key | Key properties |
|-------|-------------|----------------|
| `Creator` | `user_id` | `username`, `followers_count`, `following_count`, `media_count`, `verified`, `account_type`, `gdpr_basis`, `subject_jurisdiction`, `tos_compliant_at_ingest`, `source_id` |
| `Media` | `media_id` | `permalink`, `timestamp`, `media_type`, `caption_text`, `ftc_disclosure_status` |
| `Comment` | `comment_id` | `text`, `author_username`, `timestamp` |
| `User` | `username` | `is_bot_score` (nullable; bot scoring is 0004) |
| `Demographic` | `(country, age_range, gender)` | — |
| `Signal` | `(creator_user_id, name, run_id)` | `value`, `source`, `confidence`, `method` (`computed`\|`inferred`\|`llm`), `art9_risk`, `computed_at`, `run_id` |
| `Score` | `(creator_user_id, type, run_id)` | `type` (e.g. `brand_fit`, `fraud_risk`), `value`, `model_version`, `created_at`, `run_id`, `status` (`active`\|`deferred`) |

### 5.2 Relationships

```
(Creator)-[:HAS_MEDIA]->(Media)
(Creator)-[:HAS_SIGNAL {weight}]->(Signal)
(Creator)-[:CONTRIBUTED_TO {weight}]->(Score)
(Creator)-[:SHARES_AUDIENCE {overlap_pct}]->(Creator)       // [v2] deferred
(Creator)-[:COLLABORATED_WITH]->(Creator)                   // [v2] deferred
(Creator)-[:HAS_AUDIENCE_SEGMENT]->(Demographic)            // [v2] deferred
(Media)-[:HAS_COMMENT]->(Comment)
(Comment)-[:FROM_USER]->(User)
```

### 5.3 Constraints & Indexes (created on first load, idempotently)

```cypher
CREATE CONSTRAINT creator_user_id IF NOT EXISTS
  FOR (c:Creator) REQUIRE c.user_id IS UNIQUE;
CREATE CONSTRAINT media_media_id IF NOT EXISTS
  FOR (m:Media) REQUIRE m.media_id IS UNIQUE;
CREATE CONSTRAINT user_username IF NOT EXISTS
  FOR (u:User) REQUIRE u.username IS UNIQUE;
CREATE CONSTRAINT comment_id IF NOT EXISTS
  FOR (cm:Comment) REQUIRE cm.comment_id IS UNIQUE;
CREATE INDEX score_lookup IF NOT EXISTS
  FOR (s:Score) ON (s.type, s.created_at);
```

## 6. Idempotency & Versioning (D4)

**Entities** (`Creator`, `Media`, `User`, `Comment`, `Demographic`) are `MERGE`d on their natural
key so identity is stable across runs:

```cypher
MERGE (c:Creator {user_id: $user_id})
  ON CREATE SET c += $props, c.first_seen = $loaded_at
  ON MATCH  SET c += $props, c.last_seen  = $loaded_at
```

**Signals & Scores are versioned.** Each Stage 7 run gets a `run_id` (UUID). Signal/Score nodes
carry that `run_id` + `computed_at`/`created_at`. At the start of a run, prior signals/scores for
the handle are **superseded** — detached and deleted (or marked `superseded_at`, see open
question OQ1) — so the active graph reflects the latest run while history is auditable:

```cypher
// supersede previous run's signals for this creator
MATCH (c:Creator {user_id:$user_id})-[r:HAS_SIGNAL]->(s:Signal)
WHERE s.run_id <> $run_id
DETACH DELETE s
```

This yields: stable entity identity + no duplicate nodes on re-run (G2) while preserving the
explainability needed for Art. 22 audits over time (G4).

## 7. Compliance Invariants (carried from 0001 §9)

- C1. **Governance metadata** (`gdpr_basis`, `subject_jurisdiction`, `tos_compliant_at_ingest`,
  `source_id`) is loaded onto the `Creator` node. A load MUST fail if these are missing, unless
  `--allow-noncompliant` is passed (mirrors Stage 1 gate).
- C2. **Art. 9 risk** — any `Signal` with `art9_risk: true` keeps the flag in Neo4j; audit query
  AQ3 lists them.
- C3. **Art. 22 explainability** — every `Score` retains its `signals[]` chain via
  `CONTRIBUTED_TO {weight}` edges; AQ1 reconstructs it.
- C4. **FTC** — `ftc_disclosure_status` from Stage 3 is loaded onto `Media`; undisclosed sponsored
  posts are queryable (AQ4).
- C5. **Deferred stages** — when `05-graph.json` is absent (v1), overlap/segment edges are not
  created; the load manifest records `associations: deferred` (mirrors 0001's
  `status: deferred` placeholders).

## 8. Audit / Read Queries (D5 — delivered in this spec)

**AQ1 — Art. 22 score explanation** (the headline query):

```cypher
MATCH (c:Creator {user_id:$user_id})-[r:CONTRIBUTED_TO]->(s:Score {type:$score_type})
WHERE s.run_id = $run_id
MATCH (c)-[hs:HAS_SIGNAL]->(sig:Signal {run_id:$run_id})
RETURN c.username, s.type, s.value, s.model_version,
       collect({signal: sig.name, weight: hs.weight, value: sig.value,
                source: sig.source, confidence: sig.confidence,
                method: sig.method, art9_risk: sig.art9_risk}) AS signals
```

**AQ2 — Audience overlap / duplicate reach** (returns empty until `[v2]`):

```cypher
MATCH (a:Creator {user_id:$user_id})-[r:SHARES_AUDIENCE]->(b:Creator)
RETURN a.username, b.username, r.overlap_pct ORDER BY r.overlap_pct DESC
```

**AQ3 — Art. 9 special-category inferences for a creator:**

```cypher
MATCH (c:Creator {user_id:$user_id})-[:HAS_SIGNAL]->(s:Signal {art9_risk:true})
WHERE s.run_id = $run_id
RETURN c.username, s.name, s.value, s.method, s.confidence
```

**AQ4 — Undisclosed sponsored posts (FTC):**

```cypher
MATCH (c:Creator {user_id:$user_id})-[:HAS_MEDIA]->(m:Media)
WHERE m.ftc_disclosure_status = 'undisclosed'
RETURN c.username, m.media_id, m.permalink, m.timestamp
```

These ship as parameterized helpers (e.g. `pipeline/queries.py` or a `tools/audit.py`).

## 9. Configuration

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j          # optional, defaults to neo4j
```

Local dev assumes Neo4j 5.x (Community is sufficient; **no GDS plugin required** for this spec).

## 10. Acceptance Criteria

- A1. `--stage 7` on a handle with a valid `06-dossier.json` creates `Creator`/`Media`/`Signal`/
  `Score` nodes and their edges; `07-load-manifest.json` validates against its schema.
- A2. **Idempotency:** running `--stage 7` twice for the same handle yields identical node/edge
  counts (no duplicates). Verified by comparing counts before/after the second run.
- A3. **Art. 22:** AQ1 returns the full signal chain for an `engagement_quality` score, each with `weight`,
  `value`, `source`, `confidence`, `method`.
- A4. **Art. 9:** every Signal flagged `art9_risk` in `03-features.json` is flagged in Neo4j and
  returned by AQ3.
- A5. **Compliance gate:** loading a dossier missing governance metadata fails without
  `--allow-noncompliant` and succeeds with it.
- A6. **Deferred stages:** with no `05-graph.json`, the load succeeds, creates no `SHARES_AUDIENCE`
  edges, and the manifest records `associations: deferred`.
- A7. **Versioning:** a second run with changed signal values supersedes the prior run's Signal
  nodes; AQ1 with the new `run_id` reflects the new values.
- A8. `make validate` passes with the new `07-graph-load.schema.json`.

## 11. Open Questions

- OQ1. **Hard delete vs soft supersede** of prior-run Signal/Score nodes. Default: detach-delete
  (active graph = latest run). If long-term score history in-graph is required, switch to
  `superseded_at` soft-marking — but note JSON artifacts already retain per-run history on disk.
- OQ2. Comment/User volume — do we load all comments, or sample? (bot scoring is 0003; large
  comment loads may be deferred to 0004).
- OQ3. Multi-handle graphs share `User`/`Demographic` nodes across creators — confirm cross-handle
  merging is desired (it enables overlap detection but couples handle loads).

## 12. Future Work (out of scope here)

- Spec 0004: Neo4j GDS — Louvain (pod detection), centrality (bot detection), link prediction;
  results written back as `Signal`/`Score` nodes.
- Neo4j Bloom dashboards for non-technical brand teams.
- Cross-platform identity linkage `[v3]` (UIL) materialized as graph edges.
