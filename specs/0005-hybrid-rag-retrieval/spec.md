# Spec 0005 — Hybrid RAG Retrieval (Vector + Graph + Keyword)

**Status:** draft
**Depends on:** `0002-neo4j-graph-persistence` (the graph it retrieves over) ·
`0003-ollama-llm-graph-query` (local Ollama runtime + NL answer generation) ·
`0001-social-media-associations-profile` (signals, scores, governance it grounds answers in)
**Relates to:** `0004-neo4j-gds` (consumes GDS-derived signals — pod/centrality/community — when present; degrades gracefully when absent)
**Owner:** Pedro Mello
**Created:** 2026-05-30

---

## 0. Spec Numbering Note

Specs 0002 and 0003 both reserve **Spec 0004 for Neo4j GDS** (Louvain pod detection, centrality
bot detection, link prediction). That reservation stands. This Hybrid RAG spec therefore takes
**0005**. It does not require 0004 to function — it retrieves over whatever nodes, edges, and
`Signal`/`Score` records exist in the 0002 graph — but when 0004 has written community / centrality
/ fraud-ring signals, those become first-class retrieval and re-ranking signals (see §6.2, §7).

---

## 1. Problem Statement

Spec 0003 gives brand/analytics teams a **NL→Cypher** path: a question becomes one read-only
Cypher statement, executed, answered from the returned rows. That is exact and auditable, but it
has two structural blind spots:

- **It only finds what an exact graph pattern matches.** "Which creators are a good fit for a
  *sustainable activewear* brand?" has no single Cypher predicate. The intent is *semantic* —
  it must match meaning across bios, captions, and niche signals, not a literal property value.
  Pure graph/keyword lookup misses paraphrase ("eco-friendly gym wear", "low-waste fitness").
- **Pure semantic (vector) search misses exact terms and relationships.** Creator bios and
  captions carry literal tokens that *must* match exactly — `#ad`, `@nike`, a handle, an SKU, a
  campaign hashtag — and dense embeddings blur these. And the highest-value questions are
  *multi-hop relational*: "creators who collaborated with X **and** share audience with Y **and**
  have fraud_risk < 0.2" — which is the graph's home turf, not a vector index's.

No single retrieval mode serves influencer-marketing intent. This spec adds **Hybrid RAG**: dense
**vector** semantic search **+** **graph** multi-hop traversal **+** sparse **keyword (full-text /
BM25)** exact-term matching, fused with Reciprocal Rank Fusion (RRF), optionally re-ranked, then
handed to the existing Ollama backend (0003) to generate a grounded, cited answer.

Why hybrid specifically here:

| Capability | Needs | Mode that serves it |
|---|---|---|
| Fraud-ring / pod reasoning ("who is connected to this bot cluster?") | multi-hop traversal | **Graph** |
| Brand-fit by meaning ("eco activewear creator") | semantic similarity | **Vector** |
| Exact-term recall (`#ad`, `@nike`, handle, SKU) | lexical match | **Keyword/BM25** |
| GDPR Art. 22 explainability | signal lineage / audit trail | **Graph** (signal chain) |

All three modes live in **one store** — Neo4j 5.x already provides native vector indexes *and*
full-text (Lucene/BM25) indexes alongside the property graph — so hybrid retrieval needs **no
second database** and the fusion inputs share identity (`user_id` / `media_id`).

## 2. Goals

- **G1. Three-mode retrieval over one Neo4j store.** Dense vector search (native vector index),
  graph traversal (0002 model + 0004 signals when present), and keyword/BM25 (native full-text
  index) — no second datastore introduced.
- **G2. Local-only embeddings.** Embeddings are produced by a **local Ollama embedding model**
  (reusing the 0003 runtime; default `nomic-embed-text`, 768-dim). No creator text leaves the host
  — consistent with 0003's `data_egress: local-only` guarantee.
- **G3. Idempotent embedding backfill.** A new **Stage 8 EMBED** computes and upserts embeddings
  onto existing `Creator` and `Media` nodes (re-running produces no duplicates; only changed text
  is re-embedded). Mirrors 0002's Stage 7 idempotency contract.
- **G4. RRF fusion + optional rerank.** Per-mode ranked candidates are fused with Reciprocal Rank
  Fusion (no score normalization). An **optional** cross-encoder reranker (off by default, behind a
  flag) refines top-K→top-N precision when enabled.
- **G5. Grounded, cited, compliant generation.** The fused context is sent to the 0003 Ollama
  backend to phrase an answer **only from retrieved records**, with explicit citations (handle /
  media_id / signal) and the full Art. 22 signal lineage. Zero-result → answer says so (no
  fabrication), carrying forward 0003's grounding guarantee.
- **G6. Full provenance.** Every hybrid query writes a manifest (modes run, per-mode candidates,
  fusion weights, rerank on/off, model + embedding model, latency) extending 0003's query manifest.

## 3. Non-Goals

- **N1. No second vector database.** Qdrant / pgvector / FAISS are explicitly out of scope; Neo4j's
  native vector + full-text indexes are used. (Revisit only if scale forces it — see Future Work.)
- **N2. No GDS computation here.** Louvain / centrality / link-prediction remain **spec 0004**. This
  spec *reads* GDS signals if present; it does not compute them.
- **N3. No write path from retrieval.** Hybrid RAG is read-only over the graph (like 0003's
  NL→Cypher). The only writes are Stage 8 embedding upserts onto existing nodes.
- **N4. No hosted/cloud embeddings.** Embeddings are local-only (G2). No Voyage/OpenAI/Anthropic
  embedding calls — that would violate the off-host-egress posture.
- **N5. No multi-turn chat / agent memory.** Each hybrid query is a single stateless
  question → retrieve → fuse → answer (mirrors 0003 N4).
- **N6. No fine-tuning** of embedding or rerank models. Stock models, as-pulled.
- **N7. No replacement of 0003's NL→Cypher or 0002's static audit queries.** Hybrid RAG is an
  additive third retrieval surface; the exact paths remain the trusted fallback.

## 4. Architecture & Integration

```
                              ┌──────────────────────────────────────────────┐
 --rag "question"   ─────────►│ tools/rag.py  (Hybrid RAG orchestrator)       │
                              │                                               │
                              │  1. embed question  ─────► Ollama /api/embeddings
                              │                            (pipeline/llm/ollama_embed.py)
                              │  2a. VECTOR  ─► db.index.vector.queryNodes(...) │
                              │  2b. KEYWORD ─► db.index.fulltext.queryNodes(...)
                              │  2c. GRAPH   ─► NL→Cypher (reuse 0003 tools/ask)│──► Neo4j (read txn)
                              │  3. FUSE (RRF)  pipeline/rag/fusion.py          │
                              │  4. RERANK (optional, off)  pipeline/rag/rerank.py
                              │  5. GENERATE ─► OllamaBackend (0003)            │
                              │  6. MANIFEST ─► projects/<h>/queries/<ts>-rag.json
                              └──────────────────────────────────────────────┘

 --stage 8 (EMBED)  ─────────► pipeline/stage8_embed.py
                                 └─ Ollama embeddings → upsert c.embedding / m.embedding (idempotent)
```

- New module **`pipeline/stage8_embed.py`** (Stage 8 EMBED) and CLI
  `python3 profile_analyst.py --handle <handle> --stage 8` (and `--stage all` runs 1–8).
  New `make` target `make embed HANDLE=<handle>`.
- New module **`tools/rag.py`** and CLI flag
  `python3 profile_analyst.py --handle <handle> --rag "<natural-language question>"`.
  New `make` target `make rag HANDLE=<handle> Q="<question>"`.
- New package **`pipeline/rag/`**: `fusion.py` (RRF), `rerank.py` (optional cross-encoder),
  `retrievers.py` (vector / keyword / graph adapters).
- New module **`pipeline/llm/ollama_embed.py`** — thin client over Ollama `/api/embeddings`,
  reusing 0003's `OLLAMA_HOST` / `keep_alive` conventions.
- Reuses 0002's Neo4j driver (read-only sessions for retrieval; one write session for Stage 8) and
  0003's `OllamaBackend` for answer generation and its safety gates for the graph (NL→Cypher) leg.

### 4.1 Module breakdown

| Module | Responsibility |
|--------|----------------|
| `pipeline/stage8_embed.py` | Stage 8 EMBED: computes and upserts `Creator.embedding` / `Media.embedding` (idempotent); creates Neo4j vector + full-text indexes |
| `pipeline/llm/ollama_embed.py` | `OllamaEmbedder` — thin client over Ollama `/api/embeddings`; reuses 0003's `OLLAMA_HOST` / `keep_alive` conventions |
| `pipeline/rag/__init__.py` | Package root; exports `RRFFusion`, `CrossEncoderReranker`, `VectorRetriever`, `KeywordRetriever`, `GraphRetriever` |
| `pipeline/rag/retrievers.py` | Three retriever adapters (see §4.2) |
| `pipeline/rag/fusion.py` | RRF fusion (see §7.1) |
| `pipeline/rag/rerank.py` | Optional cross-encoder reranker (see §7.2); no-op when `RAG_RERANK=false` |
| `tools/rag.py` | `HybridRAGOrchestrator` — CLI entry point; orchestrates embed → retrieve → fuse → (rerank) → generate → manifest |

Configuration is entirely via **environment variables** (§11); there is no competing `config/rag_config.py`
module — all retrieval parameters (`RAG_VECTOR_K`, `RAG_RRF_K`, etc.) are read from the environment
at runtime, consistent with the project-wide env-var convention.

### 4.2 Class and method contracts (spec-altitude signatures)

```python
# pipeline/llm/ollama_embed.py
class OllamaEmbedder:
    """Thin client over Ollama /api/embeddings.
    Raises OllamaError (from pipeline/llm/ollama_client.py) on connection failure."""
    def __init__(self, host: str, model: str)        # host from OLLAMA_HOST; model from OLLAMA_EMBED_MODEL
    def embed(self, texts: Union[str, List[str]]) -> Union[List[float], List[List[float]]]
    def get_dimension(self) -> int                   # introspects from a probe embed; used to validate index config

# pipeline/stage8_embed.py
class Stage8EmbedProcessor:
    """Idempotent embedding upsert for Creator and Media nodes (see §5)."""
    def __init__(self, neo4j_driver, embedder: OllamaEmbedder, project_dir: Path)
    def process(self, handle: str) -> Dict[str, Any]          # returns manifest dict; emits 08-embed-manifest.json
    def _compute_embeddings(self, texts: List[str]) -> List[List[float]]
    def _upsert_embeddings(self, node_type: str, embeddings: Dict[str, List[float]])
    # node_type in ("Creator", "Media"); Creator keyed by user_id, Media keyed by media_id (per 0002 §5.1)

# pipeline/rag/retrievers.py
class VectorRetriever:
    """db.index.vector.queryNodes over creator_embeddings / media_embeddings."""
    def retrieve(self, embedding: List[float], k: int) -> List[Dict]
    # Returns list of {user_id, username, score, source: "vector"}

class KeywordRetriever:
    """db.index.fulltext.queryNodes over creator_fulltext / media_fulltext."""
    def retrieve(self, query: str, k: int) -> List[Dict]
    # Returns list of {user_id, username, score, source: "keyword"}

class GraphRetriever:
    """Delegates to 0003 tools/ask.py NL→Cypher path (all S1–S6 safety gates apply)."""
    def retrieve(self, nl_query: str, k: int) -> List[Dict]
    # Returns list of {user_id, username, score, source: "graph"}
    # Creator identity always via user_id; never POSTED — uses HAS_MEDIA per 0002 §5.2

# tools/rag.py
class HybridRAGOrchestrator:
    """Orchestrates the full hybrid RAG pipeline for a single question."""
    def __init__(self, neo4j_driver, ollama_backend, embedder: OllamaEmbedder, project_dir: Path)
    def query(self, question: str, handle: Optional[str] = None) -> Dict[str, Any]
    # handle: optional graph filter; default None → whole-graph corpus (OQ5)
    def _run_retrievers(self, embedded_q: List[float], question: str) -> Dict[str, List]
    def _write_manifest(self, results: Dict[str, Any], handle: Optional[str])
```

Generation in `HybridRAGOrchestrator.query` calls the **0003 `OllamaBackend`** directly — the
generation model is whatever 0003's config resolves (`OLLAMA_FEATURES_MODEL` or
`OLLAMA_CYPHER_MODEL`); this spec does not introduce a separate generation model env var or
hardcode any model name. Reranker model is `RAG_RERANK_MODEL` (default `bge-reranker-v2-m3`,
local-only, off by default).

### 4.3 Graceful degradation

Each retriever runs independently; a single-mode failure does not abort the query:

```python
# HybridRAGOrchestrator._run_retrievers() — spec-level pseudocode
results = {"vector": [], "keyword": [], "graph": []}
errors  = {}

for mode, retriever in [("vector", self.vector_retriever),
                         ("keyword", self.keyword_retriever),
                         ("graph", self.graph_retriever)]:
    if mode not in self.active_modes:   # RAG_MODES controls which modes are active
        continue
    try:
        results[mode] = retriever.retrieve(...)
    except Exception as e:
        errors[mode] = str(e)           # logged; mode contributes zero candidates to fusion

if all(len(r) == 0 for r in results.values()):
    raise RAGError("All retrievers returned empty — check indexes and Ollama availability")

# errors dict is written to the manifest's retriever[mode].error field (C6 provenance)
```

The manifest always records which modes succeeded and which errored, so a partial result is
auditable. At least one mode must contribute candidates; otherwise the query fails with a clear error.

### 4.4 Per-retriever manifest field layout

Each retriever contributes a block in the `<ts>-rag.json` manifest under `retrievers`:

```json
{
  "retrievers": {
    "vector": {
      "k": 50,
      "candidates": 18,
      "latency_ms": 45,
      "index": "creator_embeddings"
    },
    "keyword": {
      "k": 50,
      "candidates": 12,
      "latency_ms": 23,
      "index": "creator_fulltext"
    },
    "graph": {
      "k": 50,
      "candidates": 8,
      "latency_ms": 156,
      "cypher": "MATCH (c:Creator {user_id:$uid})-[:HAS_MEDIA]->(m:Media) ...",
      "safety_gates_passed": true
    }
  },
  "fusion": {"method": "RRF", "rrf_k": 60, "weights": {"vector": 1.0, "keyword": 1.0, "graph": 1.0}, "fused_candidates": 20},
  "rerank": {"enabled": false, "model": null},
  "generation": {"model": "<resolved-from-0003-config>", "latency_ms": null},
  "citations": [
    {"handle": "@creator_username", "user_id": "uid_123", "type": "creator"},
    {"media_id": "mid_456", "type": "media", "caption_snippet": "..."}
  ],
  "data_egress": "local-only"
}
```

Note: `graph.cypher` records the statement actually executed (post-safety-gate); `user_id` is the
canonical Creator key per 0002 §5.1 — handle/username appears as a human-readable label only.
`generation.model` is the string resolved from 0003 env config at runtime (never hardcoded here).

### 4.5 CLI and Makefile additions

```bash
# New CLI arguments on profile_analyst.py
--stage 8                   # run Stage 8 EMBED
--rag  "<question>"         # run hybrid RAG query
--modes vector,graph,keyword  # override RAG_MODES for this query (optional)
--rerank                    # override RAG_RERANK=true for this query (optional)

# New Makefile targets
make embed HANDLE=<handle>               # alias for --stage 8
make rag   HANDLE=<handle> Q="<question>" # alias for --rag
make rag-rerank HANDLE=<handle> Q="<question>"  # rag + --rerank
```

`--stage all` continues to run stages 1–8 (Stage 8 added to the all-stages chain).

### 4.6 Verification checklist

The following smoke-checks verify the architecture without requiring a full test run:

- **V1 — Module loading:** all new modules import without error: `from pipeline.stage8_embed import
  Stage8EmbedProcessor`, `from tools.rag import HybridRAGOrchestrator`, `from pipeline.rag import
  RRFFusion, VectorRetriever, KeywordRetriever, GraphRetriever`, `from pipeline.llm.ollama_embed
  import OllamaEmbedder`.
- **V2 — Graph retriever identity:** `GraphRetriever` outputs carry `user_id` (not bare `handle`);
  any generated Cypher traverses `(Creator)-[:HAS_MEDIA]->(Media)` — never `[:POSTED]` or keys
  `Creator` by `handle` property (both are wrong per 0002 §5).
- **V3 — No off-host model call in retriever or reranker:** a no-network test confirms
  `VectorRetriever`, `KeywordRetriever`, and `CrossEncoderReranker` make no HTTP call outside
  `OLLAMA_HOST` / Neo4j bolt.
- **V4 — Reranker off by default:** with `RAG_RERANK` unset (or `false`), no rerank model is
  loaded and `manifest.rerank.enabled == false`.
- **V5 — Graceful partial failure:** with the keyword index absent, the keyword retriever error is
  recorded in the manifest and the query completes on vector + graph candidates.
- **V6 — Backward compatibility:** `--stage 1` through `--stage 7` and `--ask` continue to work
  unchanged; hybrid RAG is purely additive.
- **V7 — Manifest completeness:** every `--rag` manifest contains `retrievers`, `fusion`,
  `rerank`, `answer`, `citations`, `data_egress:"local-only"`, and `asked_at` (UTC ISO).

## 5. Embeddings (Stage 8 EMBED)

### 5.1 What is embedded

| Node | Text embedded | Property |
|------|---------------|----------|
| `Creator` | `username` + `display_name` + `bio` (+ primary/secondary niche signal values when present) | `c.embedding` |
| `Media` | `caption_text` (+ extracted hashtags/mentions kept as literal tokens for the keyword index, **not** stripped) | `m.embedding` |

Hashtags and @mentions are **preserved verbatim** in the keyword full-text index (so `#ad`,
`@nike`, handles, SKUs match lexically) while also being embedded as part of caption text for the
vector index. This is the concrete reason all three modes coexist.

### 5.2 Embedding model

- Local Ollama embedding model, default **`nomic-embed-text`** (768-dim, cosine). Overridable via
  `OLLAMA_EMBED_MODEL`. Dimension and similarity function are recorded in the Stage 8 manifest and
  MUST match the Neo4j vector index config (see §10 modification to 0002).
- Alternative local models (e.g. `bge-m3`, `mxbai-embed-large`) are config-swappable; **changing
  the model or dimension requires re-running Stage 8 for all nodes** (manifest records a
  `embedding_model_version` so a mismatch is detectable and forces rebuild).

### 5.3 Idempotency (mirrors 0002 §6)

- Each node stores `embedding`, `embedding_model_version`, and a `text_hash` (hash of the embedded
  source text). Stage 8 re-embeds a node **only if** `text_hash` changed or
  `embedding_model_version` differs — otherwise it is skipped. Re-running on unchanged data is a
  no-op (zero writes). Manifest records `{embedded, skipped, reembedded}` counts.
- Stage 8 emits `08-embed-manifest.json` validated against `schemas/09-embed.schema.json`.

## 6. Retrieval Modes

A hybrid query runs the three modes in parallel (each capped, each producing a ranked candidate
list keyed by `user_id` and/or `media_id`).

### 6.1 Vector (dense, semantic)

```cypher
CALL db.index.vector.queryNodes('creator_embeddings', $k, $q_embedding)
YIELD node AS c, score
RETURN c.user_id AS id, c.username AS username, score AS vector_score
```

(plus a parallel `media_embeddings` query for caption-level matches). `$k = RAG_VECTOR_K`
(default 50). Question is embedded once via §5.2.

### 6.2 Graph (multi-hop, relational)

Reuses the **0003 NL→Cypher** path with all its safety gates (S1–S6, read-only txn) to translate
the relational part of the question into one read-only Cypher statement, then ranks returned
creators. When **0004 GDS** signals exist (e.g. `Signal {name:'community_id'|'centrality'|
'fraud_ring_id'}`), they are available to the generated Cypher and to ranking — e.g. boost/penalize
candidates by fraud-ring membership or centrality. When absent, the graph leg still traverses
`HAS_MEDIA` / `SHARES_AUDIENCE` / `COLLABORATED_WITH` / `HAS_SIGNAL` edges.

### 6.3 Keyword (sparse, BM25 / exact term)

```cypher
CALL db.index.fulltext.queryNodes('creator_fulltext', $q_text, {limit:$k})
YIELD node AS c, score
RETURN c.user_id AS id, c.username AS username, score AS keyword_score
```

(plus `media_fulltext` over captions). This is the mode that recovers `#ad`, `@handle`, SKUs, and
campaign hashtags that the vector mode blurs. `$k = RAG_KEYWORD_K` (default 50).

Any mode may be disabled per query (`--modes vector,graph,keyword`); default is all three.

## 7. Fusion & Reranking

### 7.1 Reciprocal Rank Fusion (RRF) — `pipeline/rag/fusion.py`

```python
RRF_K = 60                       # standard constant; RAG_RRF_K overridable
score[id] = Σ_over_modes  weight_mode * 1 / (RRF_K + rank_in_mode)
```

- No score normalization across modes (RRF works on ranks — robust to incomparable score scales).
- Per-mode weights are **named constants** (`RAG_MODE_WEIGHTS = {"vector":1.0,"graph":1.0,
  "keyword":1.0}`), overridable via config, recorded in the manifest (parameterizable in tests,
  mirroring 0001's "weights are named constants" convention).
- Output: a single fused ranked list of candidate ids, truncated to `RAG_FUSED_TOP_K` (default 20).

### 7.2 Optional reranker — `pipeline/rag/rerank.py`

- **Off by default** (`RAG_RERANK=false`). When enabled, a local cross-encoder
  (`RAG_RERANK_MODEL`, e.g. `bge-reranker` via Ollama or a local sentence-transformers
  cross-encoder) re-scores the fused top-K (`RAG_RERANK_INPUT`, default 50) → top-N
  (`RAG_RERANK_OUTPUT`, default 5). Adds precision at a latency cost; keeps v1 lean when off.
- Reranker, like embeddings, is **local-only** (N4). The manifest records `rerank: on|off` and the
  model when on.

## 8. Generation (reuse 0003)

The fused (or reranked) top-N candidates are expanded into a context block — each candidate's
`username`, key metrics, niche, the `Signal`/`Score` records (with `confidence`, `method`,
`art9_risk`), and matched media snippets — then sent **once** to the 0003 `OllamaBackend` to phrase
a natural-language answer. The generation prompt requires:

1. Answer **only** from the provided records (carries 0003 C5 grounding guarantee — zero results →
   the answer says so, asserts no graph facts).
2. **Cite** each claim with its source (`@handle`, `media_id`, or `signal name`).
3. For any decision-relevant ranking, surface the **Art. 22 signal lineage** (which signals drove
   the placement) — the hybrid path is advisory only; a human confirms selection.

## 9. Safety & Compliance Invariants

Carried from 0001 §9 / 0002 §7 / 0003 §6–§7, extended for hybrid retrieval:

- **C1. Graph leg inherits 0003 safety.** The NL→Cypher (graph) mode runs through 0003's S1–S6
  gates and a read-only transaction. Vector/keyword legs use only the read procedures
  `db.index.vector.queryNodes` / `db.index.fulltext.queryNodes` in read-only sessions.
- **C2. Local-only egress.** Embedding, retrieval, optional rerank, and generation all run on the
  host; the manifest records `data_egress: local-only`. No mode may call a hosted API. (If a future
  hosted embedding model is configured, Stage 8 MUST refuse unless an explicit opt-in flag is set.)
- **C3. Art. 9 surfacing.** When any retrieved candidate carries an `art9_risk:true` signal, the
  answer surfaces an Art. 9 notice; such signals are never silently summarized away (mirrors 0003
  C3). Art. 9 signal *text* remains redacted in the answer per 0001 §9.1 unless `expose_art9`.
- **C4. Art. 22 lineage.** The generated answer for any ranking includes the contributing signal
  chain (via 0002 `CONTRIBUTED_TO` / `HAS_SIGNAL`), so a ranking is explainable, not a black box.
- **C5. Governance respected.** Retrieval never returns a `Creator` whose governance gate failed in
  0002; embeddings are only computed for nodes that passed the 0002 compliance gate.
- **C6. Provenance.** Every `--rag` writes `projects/<handle>/queries/<ts>-rag.json` validated
  against `schemas/10-rag.schema.json`: `question`, `modes_run`, per-mode `candidates` (id + rank +
  score), `fusion: {method:"rrf", rrf_k, weights}`, `rerank: {on, model}`, `embedding_model`,
  `gen_model`, `fused_top` ids, `answer`, `citations[]`, `row_counts`, `latency_ms`,
  `data_egress:"local-only"`, `asked_at` (UTC ISO).

## 10. Suggested Modifications to Existing Specs

Hybrid RAG is *additive*, but two upstream specs need small, backward-compatible amendments. These
are proposed here and should be ratified into the respective specs:

### 10.1 Spec 0002 (Neo4j Graph Persistence) — **required**

- **Add embedding properties** to the node tables (§5.1): `Creator.embedding`,
  `Creator.embedding_model_version`, `Creator.text_hash`; same three on `Media`. (Nullable; only
  populated by 0005 Stage 8 — 0002 loads remain valid with them absent.)
- **Add native indexes** to §5.3 (created idempotently, but **by Stage 8**, not Stage 7, so 0002
  has no new dependency):

  ```cypher
  CREATE VECTOR INDEX creator_embeddings IF NOT EXISTS
    FOR (c:Creator) ON (c.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};
  CREATE VECTOR INDEX media_embeddings IF NOT EXISTS
    FOR (m:Media) ON (m.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};
  CREATE FULLTEXT INDEX creator_fulltext IF NOT EXISTS
    FOR (c:Creator) ON EACH [c.username, c.display_name, c.bio];
  CREATE FULLTEXT INDEX media_fulltext IF NOT EXISTS
    FOR (m:Media) ON EACH [m.caption_text];
  ```

- **Resolve 0002 OQ2** (comment/user volume): embeddings are computed on `Creator`/`Media` only in
  v1, so large comment loads remain deferrable without blocking RAG.
- *Note:* requires **Neo4j 5.13+** (vector index GA). Community edition suffices; **no GDS plugin
  required for 0005** (only for 0004).

### 10.2 Spec 0003 (Ollama Local-LLM Graph Query) — **minor**

- **Add an embedding role** to the per-role model config (§5 / §8): `OLLAMA_EMBED_MODEL`
  (default `nomic-embed-text`). 0003 already lists "embedding-based semantic search ... via a local
  Ollama embedding model" as future work — 0005 *realizes* that item; mark it delivered-by-0005.
- **Reuse, do not fork, the graph safety gates.** 0005's graph retrieval leg calls 0003's existing
  NL→Cypher path rather than re-implementing Cypher generation — so S1–S6 have a single owner.

### 10.3 Spec 0001 — none

No change. 0005 consumes 0001's signals/scores/governance as-is; explainability and Art. 9/22
posture are inherited.

## 11. Configuration

```
# Embeddings (Stage 8) + retrieval — reuses 0003's Ollama runtime
OLLAMA_EMBED_MODEL=nomic-embed-text     # local embedding model (768-dim default)
EMBED_DIMENSIONS=768                     # must match the Neo4j vector index config
RAG_VECTOR_K=50                          # per-mode candidate cap (vector)
RAG_KEYWORD_K=50                         # per-mode candidate cap (keyword/BM25)
RAG_GRAPH_K=50                           # per-mode candidate cap (graph leg)
RAG_MODES=vector,graph,keyword           # which modes to run (overridable per --rag)
RAG_RRF_K=60                             # RRF constant
RAG_MODE_WEIGHTS=vector:1.0,graph:1.0,keyword:1.0
RAG_FUSED_TOP_K=20                       # fused list truncation
RAG_RERANK=false                         # optional cross-encoder rerank (off by default)
RAG_RERANK_MODEL=bge-reranker-v2-m3      # used only when RAG_RERANK=true (local)
RAG_RERANK_INPUT=50
RAG_RERANK_OUTPUT=5
```

Plus all 0002 Neo4j config and all 0003 Ollama config (`OLLAMA_HOST`, `LLM_BACKEND`,
`OLLAMA_KEEP_ALIVE`, `ASK_*`). Assumes a running Ollama daemon with the embedding model pulled
(`ollama pull nomic-embed-text`) and Neo4j 5.13+.

## 12. Acceptance Criteria

- **A1. Embed backfill:** `--stage 8` on a handle already loaded by 0002 Stage 7 computes
  `c.embedding`/`m.embedding`, creates the vector + full-text indexes, and writes
  `08-embed-manifest.json` validating against `schemas/09-embed.schema.json`.
- **A2. Embed idempotency:** re-running `--stage 8` on unchanged data performs **zero** re-embeds
  (manifest `reembedded:0`) and creates no duplicate indexes.
- **A3. Vector retrieval:** a semantic query with no literal keyword match (e.g. "eco-friendly gym
  wear creator" against a bio reading "sustainable activewear") returns the creator via the vector
  mode, ranked, in the manifest's `candidates`.
- **A4. Keyword retrieval:** a query for an exact token (`#ad`, a handle, an SKU) returns the
  matching node via the keyword mode even when its vector score is low — proving BM25 recovers
  exact terms vector search misses.
- **A5. Graph retrieval:** a relational query ("creators who collaborated with X and share audience
  with Y") routes through the 0003 NL→Cypher path under read-only gates and contributes graph-mode
  candidates.
- **A6. Fusion:** `pipeline/rag/fusion.py` RRF-combines the three ranked lists deterministically;
  a unit test on fixed per-mode rankings yields the documented fused order. Weights are
  overridable and recorded in the manifest.
- **A7. Reranker flag:** with `RAG_RERANK=true`, the fused top-K is reranked to top-N and the
  manifest records `rerank.on=true` + model; with the default `false`, RRF output is used directly
  and no rerank model is loaded.
- **A8. Grounded + cited answer:** `--rag "<question>"` returns an answer phrased only from
  retrieved records, with `citations[]` referencing `@handle`/`media_id`/`signal`; a zero-result
  query yields an answer stating so with no fabricated facts.
- **A9. Local-only egress:** every `--rag` and `--stage 8` manifest records
  `data_egress: local-only`; no hosted API is contacted (verified by a no-network test).
- **A10. Art. 9 / Art. 22:** a query touching `art9_risk` signals surfaces an Art. 9 notice; a
  ranking answer includes the contributing signal lineage.
- **A11. Capability error:** with Ollama stopped, `--stage 8` and `--rag` exit non-zero with a
  clear "Ollama unreachable at $OLLAMA_HOST" message; with the vector index absent, `--rag` emits a
  clear "run --stage 8 first" error.
- **A12. `make validate`** passes with the new `schemas/09-embed.schema.json` and
  `schemas/10-rag.schema.json`.

## 13. Open Questions

- **OQ1. Embedding dimension lock-in.** `nomic-embed-text` is 768-dim; switching to `bge-m3`
  (1024-dim) forces an index rebuild + full re-embed. Do we pin one model in v1 (simplest) or build
  the rebuild-on-mismatch path now? Default: pin `nomic-embed-text`; manifest detects mismatch and
  errors with a "rebuild required" message.
- **OQ2. Reranker host — Ollama vs sentence-transformers.** Cross-encoders are not all available as
  Ollama models. Use an Ollama-served reranker where available, else a local sentence-transformers
  cross-encoder behind the `[rag]` optional extra? Default: optional extra; reranker off in v1.
- **OQ3. Graph-leg ranking signal.** How should graph-mode rank its returned rows for RRF — by
  traversal proximity, by a GDS centrality signal (0004), or simply by Cypher `ORDER BY`? Default:
  honor the generated `ORDER BY`; when a centrality/fraud signal is present, expose it as a weight.
- **OQ4. Media vs creator granularity in fusion.** Vector/keyword can match `Media` nodes; results
  must roll up to the owning `Creator` for ranking. Roll up by max or by sum of media scores?
  Default: max (a single strongly-matching post surfaces the creator), recorded in the manifest.
- **OQ5. Multi-handle corpus.** RAG is most useful across many loaded creators, not one. Confirm
  `--rag` operates over the **whole graph** by default (not scoped to `--handle`), with `--handle`
  as an optional filter. (Couples to 0002 OQ3 cross-handle merging.)

## 14. Future Work (out of scope here)

- **Spec 0004 dependency uplift:** once GDS (0004) ships, add fraud-ring / community / centrality
  signals as explicit RRF weights and rerank features.
- **Dedicated vector store** (Qdrant / pgvector) *only if* graph-resident vectors hit a scale or
  latency ceiling Neo4j cannot meet (N1 revisit).
- **Sparse-dense single-model hybrid** (e.g. `bge-m3` producing dense + sparse vectors) to collapse
  vector + keyword into one model.
- **Retrieval-quality eval harness:** nDCG / recall@k over a labeled fixture across mode
  combinations and rerank on/off (pairs with 0003's planned model benchmark harness).
- **Multi-turn conversational RAG** with memory, once single-shot hybrid retrieval is trusted
  (mirrors 0003 N5 deferral).
```
