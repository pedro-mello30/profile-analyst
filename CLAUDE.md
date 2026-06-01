# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Pipeline that produces a **social-media associations profile dossier** seeded from an Instagram handle.
Outputs a unified creator profile covering: niche/attributes, brand affinity, engagement quality,
sponsored-post detection, and (in later versions) cross-platform identity linkage + audience-overlap graph.

Primary use case: influencer-marketing analytics.

**Spec-Driven Development:** `specs/0001-social-media-associations-profile/spec.md` is the source
of truth for all pipeline behavior. Read it before implementing anything.

**Stack:** Python 3.11+ · Anthropic SDK (`claude-sonnet-4-6`, Stages 3+ NLP) · `pydantic` (models) ·
`jsonschema` (stage validation) · `rapidfuzz` (string similarity for linkage) · `networkx` (graph)

## Pipeline Stages

```
Stage 1  INGEST       handle → 01-raw.json          (SourceAdapter fetch; v1 = SampleAdapter)
Stage 2  NORMALIZE    → 02-normalized.json           (canonical Profile + governance metadata)
Stage 3  FEATURES     → 03-features.json             (influencer feature catalog; Claude NLP)
Stage 4  LINKAGE      → 04-linkage.json              (UIL: cross-platform candidates) [v3]
Stage 5  ASSOCIATIONS → 05-graph.json                (overlap / community / centrality) [v2]
Stage 6  DOSSIER      → 06-dossier.json + report.md  (unified dossier + provenance)
```

Each stage is idempotent — re-running overwrites only its own output artifact.

## Project Layout

```
adapters/
├── base.py              # SourceAdapter ABC (data_category, tos_compliant, gdpr_basis …)
└── sample.py            # SampleAdapter: reads local JSON fixture (v1 default)

pipeline/
├── stage1_ingest.py
├── stage2_normalize.py
├── stage3_features.py   # calls Claude API
├── stage6_dossier.py
└── compliance.py        # cross-cutting: ToS-gate, Art.9 flags, FTC detection

prompts/
└── stage3-features.md   # system prompt for Claude NLP (niche + sponsored detection)

schemas/
├── 01-raw.schema.json
├── 02-normalized.schema.json
├── 03-features.schema.json
└── 06-dossier.schema.json

specs/0001-social-media-associations-profile/
├── metadata.yml         # decision register + testable acceptance
├── spec.md              # THE source of truth
├── plan.md
├── tasks.md
└── summary.md           # Portuguese summary (written by spec-finalizer)

projects/<handle>/       # runtime artifacts (gitignored except 00-input/)
tools/
└── validate.py          # used by `make validate`
```

## Commands

```bash
python3 profile_analyst.py --handle <handle> --stage all
python3 profile_analyst.py --handle <handle> --stage 1,2,3
python3 profile_analyst.py --handle <handle> --stage 6

make validate    # validates schemas + metadata.yml
make test        # pytest tests/
make run HANDLE=<handle>
```

## Key Invariants (enforce in every stage)

- **Stage 1:** Every raw record carries `source_id`, `data_category`, `tos_compliant_at_ingest`,
  `ingested_at` (UTC ISO), `gdpr_basis`, `subject_jurisdiction`. Non-compliant adapters are
  rejected unless `--allow-noncompliant` is explicitly passed.
- **Stage 2:** Canonical `Profile` validated against `02-normalized.schema.json` before continuing.
  All governance metadata preserved from Stage 1.
- **Stage 3:** Every computed feature carries `confidence` (0.0–1.0) and `method`
  (`computed` | `inferred` | `llm`). Special-category inferences (Art. 9 risk) are flagged with
  `art9_risk: true`. Sponsored-post detection always runs; `ftc_disclosure_status` emitted.
- **Stage 6:** Every score has `signals: []` (explainability). `compliance_flags` block always
  present. Placeholders emitted for deferred stages (linkage, associations) with `status: deferred`.

## Claude API Usage (Stage 3)

Prompt template in `prompts/stage3-features.md`. The call uses:
- System message: the Stage 3 section of spec.md + the prompt template
- User message: `02-normalized.json` (or the relevant fields)
- Output validated against `03-features.schema.json` before accepting

Use `claude-sonnet-4-6`. Responses must be pure JSON matching the schema.
Include prompt caching for the system message (it's large and static per run).

## Environment Variables

```
ANTHROPIC_API_KEY=...     # Stage 3+ (Claude NLP)
ALLOW_NONCOMPLIANT=false  # Set true to bypass ToS-flag gate (test only)

# Stage 7 LOAD — Neo4j graph persistence (spec 0002)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j      # optional, defaults to neo4j

# Ollama local-LLM + NL→Cypher (spec 0003)
LLM_BACKEND=anthropic                  # anthropic | ollama  — Stage 3 backend selector
OLLAMA_HOST=http://localhost:11434     # Ollama daemon
OLLAMA_CYPHER_MODEL=qwen2.5-coder:32b  # NL→Cypher role (favor code/structured output)
OLLAMA_FEATURES_MODEL=qwen2.5:14b      # Stage 3 feature-extraction role
OLLAMA_KEEP_ALIVE=10m                  # hold model warm across a run
OLLAMA_TIMEOUT_S=120                    # Ollama HTTP read timeout (s); raise to 600 on slow CPU-only hosts (spec 0010)
ASK_MAX_ROWS=200                       # S5 row cap (injected LIMIT + client-side roof)
ASK_TIMEOUT_MS=5000                    # S5 read-transaction statement timeout
ASK_FALLBACK=true                      # Stage 3: fall back to anthropic if Ollama unreachable

# Hybrid RAG — embedding + retrieval (spec 0005)
OLLAMA_EMBED_MODEL=nomic-embed-text    # local embedding model (default 768-dim)
EMBED_DIMENSIONS=768                   # must match the Neo4j vector index config
RAG_VECTOR_K=50                        # per-mode candidate cap (vector)
RAG_KEYWORD_K=50                       # per-mode candidate cap (keyword/BM25)
RAG_GRAPH_K=50                         # per-mode candidate cap (graph leg)
RAG_MODES=vector,graph,keyword         # which modes to run (overridable per --rag)
RAG_RRF_K=60                           # RRF constant
RAG_MODE_WEIGHTS=vector:1.0,graph:1.0,keyword:1.0
RAG_FUSED_TOP_K=20                     # fused list truncation
RAG_RERANK=false                       # optional cross-encoder rerank (off by default)
RAG_RERANK_MODEL=bge-reranker-v2-m3   # used only when RAG_RERANK=true (local, [rag] extra)
RAG_RERANK_INPUT=50                    # top-K fed to reranker
RAG_RERANK_OUTPUT=5                    # top-N out of reranker
```

## Compliance Notes (read before adding any live data source)

- Instagram Basic Display API was shut down 2024-12-04. No replacement for personal accounts.
- Instagram Graph API only exposes owned Business/Creator accounts + `business_discovery` for
  public Business/Creator profiles (no follower lists, no third-party demographics).
- GDPR Art. 22 applies to any score used to make decisions affecting creators (campaign selection).
  Every such score MUST have: explainability (signals list), human-review path, opt-out mechanism.
- GDPR Art. 9 risk for any inference that may reveal health, political views, sexual orientation,
  or religion — even from public posts. Flag with `art9_risk: true`; require explicit consent.
- FTC civil penalty: ~$53k per undisclosed sponsorship violation.
- See `specs/0001-social-media-associations-profile/spec.md §9` for full compliance spec.
