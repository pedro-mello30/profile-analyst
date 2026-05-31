# Spec 0012 — Audience-Overlap Graph (Stage 5 ASSOCIATIONS, v2a)

> Status: **draft** · Owner: pedro · Depends on: 0001 (Stage 5 design §7, dossier `associations` block), 0003 (Stage 3 features consumed as similarity input — read-only)
>
> Spec 0001 §7 *designed* Stage 5 (the association graph) and left it deferred; Stage 6 emits an
> `{"associations": {"status": "deferred", "graph_summary": null}}` placeholder. This spec
> **implements the v2a slice**: build a creator–creator association graph across the cohort already on
> disk, detect communities and centrality over it **in-process with `networkx`**, and surface the
> seed handle's position in the dossier — all **offline, with no graph database, no GDS, no network,
> and no cloud egress**.

## 1. Context & motivation

Stage 5 was deferred for two reasons (0001 §7, § table row "Stage 5"): it needs **multi-profile**
data, and the original design assumed **graph-engine infrastructure**. This spec keeps it deliberately
narrow, exactly as 0011 narrowed Stage 4:

- **Multi-profile, cohort-scoped.** The cohort is every `projects/*/02-normalized.json` already on
  disk; no population-scale crawl, no remote discovery.
- **Opt-in, never on the default path.** `--stage all` stays `1,2,3,6,7,8,9`; associations runs only
  via an explicit `--stage 5`. A routine full run never builds the cohort graph.
- **No graph database, no GDS.** The original §7 design named Neo4j GDS + Leiden. This v2a slice
  builds the graph **in-memory with `networkx`** (already a core dep) and writes a single JSON
  artifact. This keeps Stage 5 off the Neo4j/Enterprise-GDS critical path, preserves the
  offline-unit-suite invariant, and matches the project's model-free / service-free subset goal
  (`docs/architecture.md` "Deployment": the `--stage 1,2,3,6` subset runs from the filesystem alone —
  Stage 5 v2a joins it).
- **Two honest edge types only.** v2a ships **content-similarity** (token-set Jaccard over niche +
  hashtag tokens) and **collaboration** (mutual @mentions / co-tags / co-sponsored brands). **True
  audience overlap (Jaccard on follower intersection) is deferred to v2b** — the pipeline has no
  follower lists (Instagram exposes none; CLAUDE.md compliance notes), so the "audience-overlap" name
  is honestly qualified rather than faked.

The deliverable is the realization of 0001 §7 v2a, nothing more: two agreement-edge families, Leiden
community detection (with a Louvain fallback), three centrality measures, the
`05-graph.schema.json` contract, the Art. 9 / Art. 22 gates, and Stage 6 surfacing of an ego-centric
view of the graph.

## 2. Goals / Non-goals

**Goals**
- `--stage 5` produces `projects/<handle>/05-graph.json` validating against
  `schemas/05-graph.schema.json` (`method_version: "v2a"`).
- Cohort discovered by globbing `projects/*/02-normalized.json`; a `<2`-member cohort raises (§7
  "graph operations require ≥ 2 creator profiles").
- Two edge families computed offline: content-similarity (Jaccard; TF-IDF cosine optional) and
  collaboration (mention / co-tag / co-sponsor), each carrying `weight`, `method`, and `signals[]`.
- Communities via **Leiden** (`leidenalg`+`igraph`, behind the `[associations]` extra) with a
  **`networkx` Louvain fallback** when the extra is absent — `community_method` records which ran.
- Three centrality measures per node (degree, PageRank, betweenness) — native `networkx`.
- `05-graph.json` is **ego-centric**: the seed handle's community, centrality, and top-N neighbors,
  plus a cohort-level `communities_summary`.
- Stage 6 replaces the deferred placeholder with the ego view, re-running the Art. 9 gate
  (defense-in-depth).
- The whole path is offline and idempotent: Stage 5 reads cohort `02`/`03` artifacts and writes only
  `05-graph.json`; two runs over an identical cohort produce an identical artifact.

**Non-goals**
- Any graph database or GDS (Neo4j is **not** touched by Stage 5; that was the v1 design and is
  dropped here). A `SAME_AS`/association writeback to Neo4j is future work.
- True audience overlap via follower-set Jaccard (v2b; no follower lists exist).
- Embedding-based content similarity (v2b; v2a uses token-set Jaccard / optional TF-IDF — no Ollama,
  no embedding service).
- Live multi-profile discovery / lookalike search against the open web (a routine full run never
  expands the cohort; cohort = what is already on disk).
- De-duplicated reach estimates with confidence intervals (0001 §7 invariant; v2b).

## 3. Design (v2a)

**Cohort discovery — `pipeline/associations/cohort.py`.** Globs `projects/*/02-normalized.json`,
loads each into the canonical `Profile`, sorts deterministically by handle, and asserts `≥2`
members (raises a typed validation error otherwise). The seed `<handle>` is always a member; a
member missing the fields a leg needs is skipped from that leg with a recorded `warnings[]` entry
(graceful degradation — never raises).

**Edges — `pipeline/associations/edges.py`.** Two families, each producing an undirected weighted
edge list with per-edge `signals[]`:

1. **content_similar** — token-set **Jaccard** over the union of niche + hashtag tokens drawn from
   each member's `03-features.json`. Edges with `weight ≥ CONTENT_SIM_THRESHOLD (= 0.60)` are kept;
   `method: "computed"`. **TF-IDF cosine via `scikit-learn` is optional** (richer; same threshold
   semantics) and selected only when the dependency is present.
2. **collaborated** — mutual @mentions, co-tagged posts, and co-sponsored brands between two members,
   computed from the cohort's `02`/`03` corpus. `weight` = normalized shared-collaboration count;
   `method: "computed"`.

**Graph + algorithms — `pipeline/associations/graph.py`.** Builds an in-memory `networkx.Graph`
(nodes = creators, edges = the union of the two families; parallel edges collapse with `edge_type`
retained). Then:
- **Communities** — **Leiden** (`leidenalg` over an `igraph` view; seeded, behind the
  `[associations]` extra). When the extra is absent, falls back to
  `networkx.community.louvain_communities` (seeded). `community_method` records `leiden|louvain`.
  Leiden is preferred (0001 §7: connected, locally-optimal partitions).
- **Centrality** (0001 §7: combine — no single measure dominates): `degree_centrality`,
  `pagerank`, `betweenness_centrality`, all native `networkx`.

**Ego view — `pipeline/associations/ego.py`.** Selects the seed node, reads its `community_id` /
`community_size` / `centrality{}`, ranks its incident edges by weight, and emits `neighbors[]`
(top-N, `EGO_TOP_N = 10`). Also rolls up `communities_summary[]` (id, size, members, `art9_risk`).

**Gate — `pipeline/associations/gate.py`.** Runs the existing `Art9Scanner` over each community's
aggregate niche/hashtag evidence; sets `art9_risk: true` on flagged communities. Enforces that every
emitted neighbor edge carries a non-empty `signals[]` (Art. 22). Art. 9-flagged community member
lists are redactable at Stage 6 unless consent is on file.

**Orchestrator — `pipeline/stage5_associations.py`.** Thin `run(handle, project_dir)`: cohort →
edges → graph → ego → gate → schema-validate → atomic write `05-graph.json`. Idempotent; touches no
other artifact and no external service.

**CLI wiring — `profile_analyst.py`.** `STAGE_MAP` gains `5 → stage5_associations.run`. `--stage all`
expansion is **unchanged** (`1,2,3,6,7,8,9`); Stage 5 is reachable only by explicit `--stage 5`.

**Stage 6 surfacing — `pipeline/stage6_dossier.py`.** If `05-graph.json` exists, Stage 6 fills the
dossier `associations` block with the ego view, re-running the Art. 9 community gate
(defense-in-depth) and redacting flagged member lists absent consent; if the artifact is absent it
keeps the existing `{"status": "deferred", "graph_summary": null}` placeholder.

## 4. Decisions

See `metadata.yml` `decisions:` for the authoritative list (D1–D9): opt-in wiring (D1), cohort by
glob with a `≥2` guard (D2), the `networkx`-in-process engine with **no Neo4j/GDS** (D3), the two
v2a edge families with TF-IDF behind an optional dep (D4), Leiden behind the `[associations]` extra
with a Louvain fallback (D5), the ego-centric `05-graph.schema.json` contract (D6), the Art. 9 /
Art. 22 gates + Stage 6 surfacing (D7), the deterministic-idempotency rules (D8), and the deferral of
true audience overlap + any graph-store writeback (D9).

## 5. Compliance

- **`≥2` cohort guard (§7).** A graph of one creator is meaningless; Stage 5 raises a typed
  validation error (exit 1) below two members.
- **Art. 9 — community membership is special-category-adjacent.** A detected community can reveal a
  protected affinity (LGBTQ+, religious, or political cluster). The `Art9Scanner` runs over each
  community's aggregate evidence and sets `art9_risk: true`; Stage 6 redacts flagged communities'
  member lists unless consent is on file. Enforced at both Stage 5 emission and Stage 6 assembly
  (defense-in-depth, mirroring the Art. 9 re-assertion invariant).
- **Art. 22 — explainability.** Every neighbor edge carries `signals[]` (≥1) — the concrete shared
  tokens / collaboration evidence behind the weight, the same bar as a dossier score. An edge with no
  explanation cannot be emitted.
- **Data minimization.** Only niche, hashtags, mentions, and brand-partner fields feed the
  similarity / collaboration computation — never engagement counts or governance internals.
- **Honesty about method.** v2a edges are `method: "computed"`; the deferred audience-overlap edge
  would be `method: "inferred"`. The IQFluence overlap bands (`<20%` … `>60%`) ship as named
  constants but are inert in v2a, documented as v2b wiring (single home for the constants).

## 6. Acceptance

Authoritative list in `metadata.yml` `acceptance:` (A1–A8, all `status: planned`): opt-in stage
wiring with `--stage all` unchanged (A1), `≥2` cohort guard raises (A2), schema-valid offline
emission with per-edge `signals[]` (A3), Leiden community + three centralities present (A4), Louvain
fallback when the `[associations]` extra is absent — recorded in `community_method` (A5), Art. 9
community flag + Stage 6 redaction (A6), Stage 6 surfacing replaces the deferred placeholder /
keeps it when the artifact is absent (A7), and `make validate` + the offline unit suite green with
the stage reaching no network and no database (A8).

## 7. Module layout / components

```
pipeline/
├── stage5_associations.py     # thin idempotent orchestrator → 05-graph.json
└── associations/
    ├── cohort.py              # glob projects/*/02-normalized.json; deterministic sort; ≥2 guard
    ├── edges.py               # content_similar (Jaccard; TF-IDF optional) + collaborated edge lists
    ├── graph.py               # networkx build; Leiden ([associations] extra) → Louvain fallback; 3 centralities
    ├── ego.py                 # ego subview → neighbors[] (EGO_TOP_N) + communities_summary[]
    └── gate.py                # Art.9 community scan + Art.22 signals enforcement
schemas/05-graph.schema.json   # draft-7; method_version enum "v2a"
```
Plus edits to `profile_analyst.py` (`STAGE_MAP`), `pipeline/stage6_dossier.py` (associations
surfacing), `pipeline/models.py` (`AssociationGraph`, `AssociationNeighbor`, `CommunitySummary`),
`pyproject.toml` (`[associations]` extra: `leidenalg`, `igraph`; `scikit-learn` optional for TF-IDF),
and `tools/validate.py` (register the new schema).

## 8. Test plan

- **Offline unit suite (`tests/associations/`).** Edge families against synthetic cohorts
  (high/low/no overlap; shared vs disjoint mentions); Jaccard threshold behavior; community
  detection on a known two-cluster graph; centrality ordering on a star/bridge topology; the Louvain
  fallback path when `leidenalg` is import-blocked; the gate truth table (Art. 9 flag → redaction).
- **Stage integration.** A committed multi-profile fixture under `projects/*` → schema-valid
  `05-graph.json`; the `≥2` guard raises on a single-member cohort; `_parse_stages` proves `all`
  excludes 5 and `--stage 5` includes it.
- **Stage 6.** Ego view replaces the placeholder; an absent `05-graph.json` keeps
  `{"status":"deferred"}`; an Art. 9-flagged community has its member list redacted absent consent.
- **Determinism.** Two runs over an identical cohort produce a byte-identical `05-graph.json`. The
  unit suite stays offline (Architecture Invariant) — no network, no database.

## 9. Future work (v2b and beyond)

- **True audience overlap:** Jaccard on follower-set intersection (or cosine on audience-attribute
  vectors) once a consent-based follower source exists — `method: "inferred"`, banded by the
  IQFluence thresholds already declared as constants.
- **Embedding-based content similarity:** cosine over the Stage 8 `nomic-embed-text` vectors instead
  of token-set Jaccard, for richer niche matching.
- **De-duplicated reach** estimates with confidence intervals (0001 §7 invariant).
- **Graph-store writeback:** persist association edges as Neo4j relationships so `/ask` and `/rag` can
  traverse them — re-introducing the graph engine as an *optional* sink, never a Stage 5 dependency.
- **Lookalike discovery:** expand the cohort beyond on-disk profiles via a discovery adapter (its own
  governance posture and ToS review).
