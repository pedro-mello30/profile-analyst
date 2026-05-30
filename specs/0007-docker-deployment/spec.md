# Spec 0007 — Docker Deployment & Service Orchestration

**Status:** draft
**Depends on:** `0001-social-media-associations-profile` (the pipeline image runs) ·
`0002-neo4j-graph-persistence` (Neo4j service) · `0003-ollama-llm-graph-query` (Ollama service +
NL→Cypher served via API) · `0005-hybrid-rag-retrieval` (hybrid RAG served via API) ·
`0006-mlflow-observability` (MLflow + PostgreSQL + MinIO services)
**Owner:** Pedro Mello
**Created:** 2026-05-30
**Source of truth:** this document. Read before implementing anything under `docker/`,
`Dockerfile`, `compose.yaml`, or `api/`.

---

## 1. Problem Statement

The profile-analyst system has grown from a single Python pipeline (0001) into a multi-service
platform: it now requires **Neo4j 5.13+** (graph persistence + native vector/full-text indexes,
0002/0005), a local **Ollama** runtime (NL→Cypher and local feature extraction, 0003; embeddings,
0005), the **Anthropic API** (default Stage 3 backend, 0001), and a self-hosted **MLflow** server
backed by **PostgreSQL + MinIO** for observability (0006). Each spec documents its own env vars and
"assumes a running X daemon" — but nothing wires them together.

This creates three concrete problems:

- **No reproducible environment.** Bringing the system up means manually installing Neo4j, pulling
  Ollama models, starting `mlflow server` + Postgres + MinIO, exporting a dozen env vars, and
  hoping versions match. There is no single source of truth for the runtime topology.
- **No service surface for queries.** `--ask` (0003) and `--rag` (0005) are CLI-only. They are the
  *interactive* surface for brand/analytics teams, yet there is no way to expose them without
  shelling into the pipeline. The batch pipeline (`--stage all`: 1, 2, 3, 6, 7, 8, 9) is correctly
  one-shot, but querying needs a long-running endpoint.
- **No ordering / readiness contract.** Stage 7 needs Neo4j up; `--ask` needs both Neo4j and
  Ollama; Stage 8 needs Ollama + the embedding model pulled; observability needs MLflow reachable.
  Today this ordering is tribal knowledge.

This spec adds **Docker containerization and a single `docker compose` topology** that builds the
pipeline image, runs every backing service with the correct versions, wires all prior-spec config
together, and exposes a thin read-only **FastAPI** service for `/ask` and `/rag`. It changes **no
pipeline logic** — it packages and orchestrates what 0001–0006 already define.

## 2. Goals

- **G1. One-command full stack.** `docker compose up` brings up Neo4j, Ollama, MLflow (+ PostgreSQL
  + MinIO), and the pipeline API with correct versions, healthchecks, and start ordering.
- **G2. Single multi-stage pipeline image.** One `Dockerfile` produces a lean, non-root runtime
  image that serves **both** run modes — one-shot CLI (`profile_analyst.py …`) and the long-running
  API — with no logic forked between them.
- **G3. CLI parity in a container.** `docker compose run --rm app --handle <h> --stage all` runs the
  full batch pipeline (stages 1, 2, 3, 6, 7, 8, 9) against the composed services, producing the same schema-valid
  artifacts as a bare-metal run, including the Art.17 `erase` / `gc` subcommands.
- **G4. Read-only query API.** A FastAPI service (`api/`) exposes `POST /ask` (0003 NL→Cypher) and
  `POST /rag` (0005 hybrid RAG) by calling the **existing** `tools/ask.py` / `tools/rag.py`
  functions — no new analytics, no new safety logic. Plus `GET /healthz` for readiness.
- **G5. GPU-backed Ollama.** The `ollama` service is provisioned for NVIDIA GPU passthrough (NVIDIA
  Container Toolkit) and a one-time model-pull step pulls the models the prior specs default to.
- **G6. Config as a single wiring point.** Every env var defined across 0001–0006 is set in one
  place (compose env + `.env`), with secrets injected at runtime — never baked into the image.
- **G7. Persistence & compliance preserved.** Named volumes for service state; `projects/` is
  bind-mounted to the host so artifacts, retention, and GDPR erasure/`gc` operate on durable,
  inspectable files exactly as in 0001 §9.

## 3. Non-Goals

- **N1. No pipeline-logic changes.** Stages 1, 2, 3, 6, 7, 8, 9 (the full `--stage all`
  sequence), scoring, compliance gates, and CLI flags are untouched. This spec only builds,
  packages, and orchestrates. The sole net-new code is the thin FastAPI wrapper (G4), which
  delegates to existing functions.
- **N2. No new analytics or query path.** The API does not add a third retrieval mode or new Cypher;
  it surfaces 0003/0005 as-is, inheriting their safety gates (0003 S1–S6, read-only sessions).
- **N3. No multi-host orchestration.** Kubernetes / Swarm / Nomad are out of scope; this is a
  single-host Docker Compose deployment (consistent with 0006 N2). Helm/k8s is Future Work.
- **N4. No managed/cloud datastores.** Neo4j Aura, RDS, S3 are out of scope — services run as
  local containers (Neo4j Community, Postgres, MinIO), matching the self-hosted posture of 0006 D1.
- **N5. No CI/CD pipeline or image registry publishing.** Building and pushing images to a registry,
  and GitHub Actions wiring, are Future Work.
- **N6. No write path from the API.** `/ask` and `/rag` are strictly read-only (mirrors 0003 N2,
  0005 N3). Loading/embedding remain CLI stages run via `docker compose run`.
- **N7. No GDS.** The `neo4j` image does **not** bundle the GDS plugin (consistent with 0002/0005).
  Spec 0004 (neo4j-gds) defines the algorithms; adding the plugin is a one-line change deferred to
  that spec's implementation track.

## 4. Architecture & Topology

```
                            docker compose (single host)
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                            │
│  app:api  (FastAPI, long-running)        app:cli  (one-shot, run --rm)     │
│   ├─ POST /ask   → tools/ask.py           profile_analyst.py --stage all   │
│   ├─ POST /rag   → tools/rag.py           profile_analyst.py erase | gc    │
│   └─ GET  /healthz                              │                          │
│        │  (same image, ENTRYPOINT switches on mode)                        │
│        └───────────────┬───────────────┬────────┴──────────┐              │
│                        ▼               ▼                   ▼               │
│                   ┌────────┐      ┌─────────┐         ┌─────────┐          │
│                   │ neo4j  │      │ ollama  │         │ mlflow  │          │
│                   │ 5.13+  │      │ (GPU)   │         │ server  │          │
│                   └───┬────┘      └─────────┘         └────┬────┘          │
│                       │ volume        │ volume            │                │
│                   neo4j_data      ollama_models     ┌──────┴──────┐        │
│                                                     ▼             ▼        │
│                                               ┌──────────┐  ┌─────────┐    │
│                                               │ postgres │  │  minio  │    │
│                                               │ (backend │  │(artifact│    │
│                                               │  store)  │  │  store) │    │
│                                               └──────────┘  └─────────┘    │
│                                                                            │
│  host bind-mount:  ./projects  ⇄  /app/projects   (artifacts, erasure, gc) │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Services

| Service | Image | Purpose | Volume | Healthcheck |
|---------|-------|---------|--------|-------------|
| `app-api` | built from `Dockerfile` (target `runtime`) | Long-running FastAPI: `/ask`, `/rag`, `/healthz` | `./projects` (bind) | `GET /healthz` 200 |
| `app-cli` | same image | One-shot pipeline / erase / gc (run via `docker compose run --rm`) | `./projects` (bind) | n/a (one-shot) |
| `neo4j` | `neo4j:5.13-community` (or newer 5.x) | Graph store + vector/full-text indexes | `neo4j_data`, `neo4j_logs` | `cypher-shell "RETURN 1"` |
| `ollama` | `ollama/ollama:latest` (pinned digest) | Local LLM + embeddings, **GPU** | `ollama_models` | `GET /api/tags` 200 |
| `ollama-pull` | `ollama/ollama` (init, `restart: "no"`) | One-shot: pull the default models, then exit | shares `ollama_models` | n/a |
| `mlflow` | built mini-image (`docker/mlflow.Dockerfile`) or `ghcr.io/mlflow/mlflow` | Tracking server | — (state in Postgres/MinIO) | `GET /health` 200 |
| `postgres` | `postgres:16` | MLflow backend (metadata) store | `mlflow_pg` | `pg_isready` |
| `minio` | `minio/minio` | MLflow artifact store (S3 API) | `minio_data` | `mc ready` / `/minio/health/live` |

`app-api` and `app-cli` are the **same built image** with different commands; `app-cli` is not a
"running" service — it is invoked on demand and removed (`--rm`).

### 4.2 The pipeline image (`Dockerfile`)

Multi-stage:

1. **`builder`** — `python:3.11-slim`; installs build deps; `pip install` the project (core deps:
   `anthropic`, `pydantic`, `jsonschema`, `rapidfuzz`, `networkx`, `neo4j`, plus the new `fastapi`
   + `uvicorn[standard]`). Optional extras (`[uil]`, `[rag]`) are build-args, default off.
2. **`runtime`** — `python:3.11-slim`; copies the installed venv + app source; creates a non-root
   `appuser` (UID 10001); `WORKDIR /app`; declares `VOLUME /app/projects`.

- **`ENTRYPOINT`** is a small `docker/entrypoint.sh` that branches on the first arg:
  `api` → `uvicorn api.main:app --host 0.0.0.0 --port 8000`; anything else → `python
  profile_analyst.py "$@"` (so `run --rm app --handle x --stage all` and `run --rm app erase
  --handle x` both work, and `up` starts the API).
- No secrets in any layer; `.env` / compose `environment` inject at runtime (G6, §7 C1).
- Image runs as non-root; `projects/` is writable because it is a bind mount owned appropriately
  (documented in README; `entrypoint.sh` does not `chown` host mounts).

### 4.3 The API (`api/`) — the only net-new code

```
api/
├── __init__.py
├── main.py        # FastAPI app: /ask, /rag, /healthz; loads settings; init_tracing() (0006)
├── models.py      # pydantic request/response: AskRequest{question, handle?}, RagRequest{question, handle?, modes?}
└── deps.py        # shared Neo4j driver + Ollama client lifecycle (startup/shutdown)
```

- `POST /ask` → calls the **existing** `tools/ask.py` entrypoint function (NL→Cypher), returns its
  answer + the manifest it already writes to `projects/<h>/queries/`. Inherits 0003 S1–S6 + read-only
  txn unchanged.
- `POST /rag` → calls the **existing** `tools/rag.py` entrypoint function (hybrid retrieval), returns
  answer + citations + manifest. Inherits 0005 fusion/safety unchanged.
- `GET /healthz` → returns 200 only when Neo4j and Ollama are reachable (used by compose
  healthcheck and `depends_on`).
- If `OBSERVABILITY_ENABLED=true`, `main.py` calls `init_tracing()` once at startup (0006 §6.1); the
  request handlers are the `influencer_rag` CHAIN entrypoint (0006 §6.3) — wiring only, no new spans
  defined here.

## 5. Startup Ordering & Readiness

`depends_on` with `condition: service_healthy` enforces the dependency graph the prior specs imply:

```
postgres ─┐
minio ────┤→ mlflow (healthy) ─┐
neo4j ────────────────────────┤→ app-api (healthy gate before accepting traffic)
ollama ──→ ollama-pull (done) ─┘
```

- `app-api` starts only after `neo4j`, `ollama`, and (when `OBSERVABILITY_ENABLED=true`) `mlflow`
  report healthy.
- `ollama-pull` runs `ollama pull` for the default models (`qwen2.5-coder:32b`, `qwen2.5:14b`,
  `nomic-embed-text` — from 0003 §5 / 0005 §5.2) then exits 0; it gates nothing except a documented
  "models present" precondition for `--ask`/`--rag`/`--stage 8`. Model set is overridable via
  `OLLAMA_PULL_MODELS`.
- `app-cli` invocations (`docker compose run`) do not auto-pull; they assume the stack is up.

## 6. GPU Provisioning (Ollama)

Per the decision to require GPU:

```yaml
ollama:
  image: ollama/ollama   # pin by digest in the real file
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
  environment:
    - OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE:-10m}
  volumes:
    - ollama_models:/root/.ollama
```

- Host prerequisite (documented in README, **not** managed by this spec — mirrors 0003 N6): NVIDIA
  driver + **NVIDIA Container Toolkit** installed and `docker info` shows the `nvidia` runtime.
- The 32B Cypher model (0003 §5.1 default) needs ~20 GB VRAM; README documents lighter overrides
  (`OLLAMA_CYPHER_MODEL=mistral-small`, `OLLAMA_PULL_MODELS=...`) for smaller GPUs.
- **WSL2 note:** this repo's dev host is WSL2; GPU passthrough requires a recent NVIDIA Windows
  driver + WSL CUDA. README documents the check; CPU-only fallback is the lighter-model override,
  not a goal of this GPU-required spec.

## 7. Configuration & Secrets

A single `.env` (git-ignored; `/.env.example` committed) is the one wiring point. Compose maps it to
every prior-spec variable. **Secrets are injected at runtime; never in the image (N1/G6).**

```
# --- App / API ---
LLM_BACKEND=anthropic                 # 0001/0003: anthropic | ollama
ANTHROPIC_API_KEY=                    # secret (0001) — required when LLM_BACKEND=anthropic
ALLOW_NONCOMPLIANT=false              # 0001 ToS gate
API_PORT=8000

# --- Neo4j (0002) ---
NEO4J_URI=bolt://neo4j:7687           # service DNS name inside the compose network
NEO4J_USER=neo4j
NEO4J_PASSWORD=                       # secret
NEO4J_DATABASE=neo4j
NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}    # consumed by the neo4j image itself

# --- Ollama (0003 / 0005) ---
OLLAMA_HOST=http://ollama:11434       # service DNS name
OLLAMA_CYPHER_MODEL=qwen2.5-coder:32b
OLLAMA_FEATURES_MODEL=qwen2.5:14b
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_KEEP_ALIVE=10m
OLLAMA_PULL_MODELS=qwen2.5-coder:32b,qwen2.5:14b,nomic-embed-text
ASK_FALLBACK=true
ASK_MAX_ROWS=200
ASK_TIMEOUT_MS=5000

# --- Hybrid RAG (0005) ---
EMBED_DIMENSIONS=768
RAG_MODES=vector,graph,keyword
RAG_RERANK=false

# --- MLflow / Observability (0006) ---
OBSERVABILITY_ENABLED=true
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_EXPERIMENT=influencer-rag-observability
MLFLOW_EXPERIMENT_EVAL=influencer-rag-eval
# MLflow backend wiring
POSTGRES_USER=mlflow
POSTGRES_PASSWORD=                    # secret
POSTGRES_DB=mlflow
MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:${POSTGRES_PASSWORD}@postgres:5432/mlflow
MLFLOW_ARTIFACTS_DESTINATION=s3://mlflow/
MINIO_ROOT_USER=                      # secret
MINIO_ROOT_PASSWORD=                  # secret
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=${MINIO_ROOT_USER}
AWS_SECRET_ACCESS_KEY=${MINIO_ROOT_PASSWORD}
```

- Inside the compose network, `NEO4J_URI`/`OLLAMA_HOST`/`MLFLOW_TRACKING_URI` use **service names**,
  not `localhost` — overriding the prior specs' localhost defaults (which remain correct for
  bare-metal runs).
- `.env.example` ships with empty secrets and safe non-secret defaults; the README documents
  generating strong values. A future hardening step may move secrets to Docker secrets / a vault
  (Future Work); env injection is the v1 baseline.

## 8. Persistence, Retention & Compliance (carried from 0001 §9 / 0002 §7)

- **C1. No secrets in image.** Verified by acceptance A7 (`docker history` shows no secret values;
  image scan finds no baked key).
- **C2. Artifacts on the host.** `./projects` is a bind mount, so `06-dossier.json`, query manifests
  (0003/0005), and all stage artifacts persist on the host and remain inspectable. The Art.17
  `erase --handle` and `gc` subcommands (0001 §9.1) run via `docker compose run --rm app erase
  --handle <h>` and operate on the same mounted tree — erasure is real on the host filesystem.
- **C3. Service state in named volumes.** `neo4j_data`, `ollama_models`, `mlflow_pg`, `minio_data`
  survive restarts; `docker compose down -v` is the documented full wipe (incl. the graph copy of
  personal data — relevant to the 0002 Future-Work graph-erasure path).
- **C4. Local-only egress preserved.** With `LLM_BACKEND=ollama`, no creator data leaves the host
  (0003 C4 / 0005 C2); the compose network is internal except for the published API/UI ports.
  With `LLM_BACKEND=anthropic`, Stage 3 calls the Anthropic API exactly as 0001 specifies — the only
  intentional egress, gated by the operator's choice of backend.
- **C5. Art. 9 / Art. 22 unchanged.** The API surfaces 0003/0005 answers verbatim, so Art. 9
  notices and Art. 22 signal lineage are carried through unmodified; MLflow tracing (0006 D9)
  redaction still applies when `OBSERVABILITY_ENABLED=true`.
- **C6. Compliance gate honored.** `--allow-noncompliant` (0001 Stage 1 / 0002 C1) is passed through
  as a CLI arg to `docker compose run --rm app …`; it is **not** a compose default (stays `false`).

## 9. Files Added

```
Dockerfile                     # multi-stage pipeline image (builder → runtime)
compose.yaml                   # the full topology (§4.1)
compose.gpu.yaml               # optional: extra GPU tuning / override (documented)
.dockerignore                  # excludes projects/, .git, tests caches, .env
.env.example                   # committed; empty secrets + safe defaults (§7)
docker/
├── entrypoint.sh              # api | <cli args> branch (§4.2)
├── mlflow.Dockerfile          # mlflow + psycopg2 + boto3 mini-image (0006 §14 deps)
└── healthcheck-api.sh         # curl /healthz wrapper (optional)
api/
├── __init__.py
├── main.py                    # FastAPI: /ask /rag /healthz (§4.3)
├── models.py
└── deps.py
```

`Makefile` gains targets (consistent with the existing `make` UX in 0001/0002/0003/0005):

```
make up            # docker compose up -d (full stack)
make down          # docker compose down
make pull-models   # run the ollama-pull init service
make app ARGS="--handle sample --stage all"   # docker compose run --rm app $ARGS
make api-logs      # docker compose logs -f app-api
```

## 10. Acceptance Criteria

- **A1. Full stack up.** `docker compose up -d` brings `neo4j`, `ollama`, `mlflow`, `postgres`,
  `minio`, and `app-api` to healthy; `docker compose ps` shows all healthy and `ollama-pull` exited 0.
- **A2. Image builds, non-root.** `docker build` succeeds; the running container's process is
  `appuser` (UID 10001), not root (`docker exec app-api id -u` → `10001`).
- **A3. CLI parity.** `docker compose run --rm app --handle sample --stage all` produces
  `projects/sample/01..08` artifacts + `report.md` on the host bind mount, each schema-valid
  (same result as a bare-metal run; 0001 A2 holds inside the container).
- **A4. Stage 7 load works composed.** `docker compose run --rm app --handle sample --stage 7`
  populates the composed `neo4j` (Creator/Media/Signal/Score nodes) and writes
  `07-load-manifest.json` (0002 A1 holds against the container Neo4j).
- **A5. Ask API.** `POST /ask {"question":"list undisclosed sponsored posts for sample"}` returns a
  grounded answer and writes a query manifest under `projects/sample/queries/`; an injected mutation
  question is rejected by 0003's gates (0003 A1/A2 hold via the API).
- **A6. RAG API.** With Stage 8 run, `POST /rag {"question":"eco-friendly gym wear creator"}` returns
  an answer with `citations[]` and writes a `*-rag.json` manifest; zero-result queries say so
  (0005 A8 holds via the API).
- **A7. No baked secrets.** `docker history --no-trunc <image>` and a layer grep show no
  `ANTHROPIC_API_KEY`/`NEO4J_PASSWORD`/MinIO secret values; the image runs only after secrets are
  supplied via env at runtime.
- **A8. GPU reservation present.** `docker compose config` shows the `nvidia` device reservation on
  the `ollama` service; on a GPU host, `docker compose exec ollama nvidia-smi` succeeds.
- **A9. Readiness ordering.** Stopping `neo4j` makes `GET /healthz` return non-200 and `app-api`
  unhealthy; it recovers when `neo4j` is healthy again (no crash loop).
- **A10. Observability wiring.** With `OBSERVABILITY_ENABLED=true`, a `/rag` call produces a trace in
  the composed MLflow (one `CHAIN` with nested spans, 0006 A1); with `OBSERVABILITY_ENABLED=false`,
  no tracking-server calls are made and the API still answers (0006 A4/A5 hold).
- **A11. Erasure on host.** `docker compose run --rm app erase --handle sample` removes
  `projects/sample/` on the host and returns an erasure receipt (0001 Art.17 path holds in-container).
- **A12. `make validate` passes** with the new spec's `metadata.yml`; no schema changes are required
  by this spec (it adds no new artifact types).

## 11. Open Questions

- **OQ1. MLflow image — build vs upstream.** Use the official `ghcr.io/mlflow/mlflow` image plus a
  pip layer for `psycopg2-binary`+`boto3`, or a small custom `docker/mlflow.Dockerfile`? Default:
  custom mini-Dockerfile (explicit deps, pinned versions; matches 0006 §14).
- **OQ2. Single API container vs CLI-also-served.** Should batch stages also be triggerable via the
  API (e.g. `POST /run`), or stay strictly `docker compose run` one-shots? Default: one-shots only —
  keeps the API read-only (N6) and the batch path idempotent/observable on the host.
- **OQ3. Ollama pull at build vs runtime.** Baking 20 GB of models into the image is huge and
  rebuild-hostile; the `ollama-pull` init service pulls at first run into a volume instead. Default:
  runtime pull via init service (chosen above). Confirm acceptable cold-start cost.
- **OQ4. Image registry & tags.** Local-build only for v1, or also publish tagged images to a
  registry (GHCR)? Default: local build only; registry/CI is Future Work (N5).
- **OQ5. Resource limits.** Should compose set memory/CPU limits per service (esp. Neo4j heap,
  `NEO4J_server_memory_heap_max_size`)? Default: document recommended values in `.env.example`; do
  not hard-cap in v1 (single-host dev posture).

## 12. Future Work (out of scope here)

- **CI/CD + registry:** GitHub Actions to build, scan, and push tagged images; SBOM generation.
- **Kubernetes/Helm chart** for multi-host production (supersedes the single-host N3 limit).
- **Docker secrets / vault** integration to replace `.env` secret injection (§7 hardening).
- **GDS service profile:** add the GDS plugin to the `neo4j` service when spec 0004 (neo4j-gds)
  is implemented — one-line change reserved here, N7.
- **Read-only Neo4j role** for the API service (defense-in-depth for 0003 S3), provisioned at
  compose init.
- **Observability of the API itself:** container metrics (cAdvisor/Prometheus) feeding the 0006
  deferred alerting (0006 N1).
