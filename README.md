# profile-analyst

A staged, compliance-first Python pipeline that ingests an Instagram handle and produces a
**unified creator associations dossier**: niche classification, engagement quality, brand affinity,
sponsored-post detection, cross-platform identity linkage, and audience-overlap graph.

Primary use case: influencer-marketing analytics with fully explainable, GDPR-compliant scores.

---

## Pipeline

```
Stage 1  INGEST        handle → projects/<handle>/01-raw.json
Stage 2  NORMALIZE     → 02-normalized.json       canonical Profile + governance metadata
Stage 3  FEATURES      → 03-features.json          Claude NLP — niche, engagement, brand
Stage 4  LINKAGE       → 04-linkage.json           cross-platform identity candidates  [v3]
Stage 5  ASSOCIATIONS  → 05-graph.json             overlap / community / centrality     [v2]
Stage 6  DOSSIER       → 06-dossier.json + report.md
Stage 7  LOAD          → Neo4j graph persistence
Stage 8  EMBED         → embedding backfill (hybrid RAG)
Stage 9  GDS           → graph data-science algorithms
```

Each stage is idempotent — re-running overwrites only its own output artifact.

---

## Stack

- **Python 3.11+**
- **Anthropic SDK** (`claude-sonnet-4-6`) — Stage 3 NLP; optional Ollama backend
- **Pydantic** — data models
- **jsonschema** — per-stage artifact validation
- **Neo4j** — graph persistence (Stage 7+)
- **networkx / igraph / leidenalg** — graph algorithms
- **rapidfuzz** — string similarity for cross-platform linkage
- **FastAPI / uvicorn** — REST API layer
- **MLflow** — observability and evaluation harness
- **Docker Compose** — local multi-service stack
- **AWS Fargate** — cloud deployment (Terraform-managed)

---

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Copy and fill in credentials
cp .env.example .env   # set ANTHROPIC_API_KEY at minimum

# Run the full pipeline on the bundled sample fixture
make run HANDLE=sample

# Run specific stages
python3 profile_analyst.py --handle sample --stage 1,2,3

# Ask a natural-language question against the graph
make ask HANDLE=sample Q="Which brands does this creator mention most?"
```

---

## Project Layout

```
adapters/
├── base.py              SourceAdapter ABC — governance metadata contract
└── sample.py            SampleAdapter: reads local JSON fixture (v1 default)

pipeline/
├── stage1_ingest.py
├── stage2_normalize.py
├── stage3_features.py   Claude API call + schema validation
├── stage6_dossier.py
└── compliance.py        ToS-gate, Art.9 flagging, FTC detection

prompts/
└── stage3-features.md   System prompt for Stage 3 NLP

schemas/
├── 01-raw.schema.json
├── 02-normalized.schema.json
├── 03-features.schema.json
└── 06-dossier.schema.json

specs/                   Spec-Driven Development — one folder per spec
├── 0001-social-media-associations-profile/
├── 0002-neo4j-graph-persistence/
├── 0003-ollama-llm-graph-query/
├── 0004-neo4j-gds/
├── 0005-hybrid-rag-retrieval/
├── 0006-mlflow-observability/
├── 0007-docker-deployment/
├── 0008-aws-deployment/
├── 0009-frontend-dashboard/
├── 0010-local-llm-runtime-reliability/
├── 0011-cross-platform-linkage/
├── 0012-audience-overlap-graph/
└── 0013-self-healing-harness/

api/                     FastAPI application
worker/                  Background task worker
frontend/                React dashboard (Vite)
deploy/aws/              Terraform + ECS task definitions
observability/           MLflow evaluation harness
tools/
├── validate.py          make validate
└── heal_sweep.py        self-healing retry sweep (spec 0013)

projects/<handle>/       Runtime artifacts (gitignored except 00-input/)
```

---

## Commands

| Command | Description |
|---------|-------------|
| `make run HANDLE=<handle>` | Full pipeline run |
| `make run HANDLE=<handle> STAGE=1,2,3` | Specific stages |
| `make load HANDLE=<handle>` | Stage 7 — load graph into Neo4j |
| `make gds HANDLE=<handle>` | Stage 9 — graph data-science |
| `make ask HANDLE=<handle> Q="..."` | NL→Cypher graph query |
| `make embed HANDLE=<handle>` | Stage 8 — embedding backfill |
| `make rag Q="..."` | Hybrid RAG query |
| `make rag-rerank Q="..."` | RAG + cross-encoder reranker |
| `make eval` | RAG quality evaluation |
| `make sweep` | HealSweep — aggregate retry failures |
| `make validate` | Validate schemas + metadata.yml |
| `make test` | pytest test suite |
| `make test-cov` | Tests with coverage report |
| `make lint` | Ruff lint + autofix |
| `make up` / `make down` | Docker Compose stack |
| `make pull-models` | Pull Ollama models into volume |
| `make frontend-dev` | React dev server (localhost:8000 API) |
| `make frontend-deploy` | Build + S3 sync + CloudFront invalidate |

---

## Environment Variables

```bash
# Required for Stage 3+
ANTHROPIC_API_KEY=...

# ToS bypass (test only)
ALLOW_NONCOMPLIANT=false

# Stage 7 — Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j

# Stage 3 backend (anthropic | ollama)
LLM_BACKEND=anthropic
OLLAMA_HOST=http://localhost:11434
OLLAMA_FEATURES_MODEL=qwen2.5:14b
OLLAMA_CYPHER_MODEL=qwen2.5-coder:32b
OLLAMA_KEEP_ALIVE=10m
OLLAMA_TIMEOUT_S=120        # raise to 600 on CPU-only hosts
ASK_FALLBACK=true           # fall back to Anthropic if Ollama unreachable

# Hybrid RAG (spec 0005)
OLLAMA_EMBED_MODEL=nomic-embed-text
EMBED_DIMENSIONS=768
RAG_MODES=vector,graph,keyword
RAG_FUSED_TOP_K=20
```

---

## Compliance

Every pipeline output is designed for GDPR Art. 22 compliance:

- **Explainable scores** — every metric emits `signals: []` identifying contributing evidence.
- **Art. 9 flagging** — inferences that may reveal health, political views, sexual orientation, or religion are flagged `art9_risk: true` and require explicit consent.
- **FTC detection** — `ftc_disclosure_status` is always emitted by Stage 3.
- **ToS gate** — non-compliant adapters are rejected at ingest unless `--allow-noncompliant` is passed.
- **Human-review path** — required for any score used in automated campaign-selection decisions.

> The Instagram Basic Display API was shut down 2024-12-04. v1 ships `SampleAdapter` (local JSON fixture). Live adapters are deferred to v2.

---

## Development

```bash
pip install -e ".[dev,graph,associations,rag,observability]"
make validate
make test
```

The `specs/` directory is the source of truth. No code change is valid without a corresponding spec section that justifies it.
