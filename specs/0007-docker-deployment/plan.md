# Plan 0007 — Docker Deployment & Service Orchestration

Derived from `spec.md`. Single-PR-per-track landing; tracks are dependency-ordered.
This spec **packages and orchestrates** the existing 0001–0006 system — it changes no
pipeline logic, schemas, or analytics. The only net-new code is a thin read-only FastAPI
wrapper (`api/`) that delegates to the existing `tools/ask.py` / `tools/rag.py`. Follows
the per-spec discipline of 0002 (idempotent, additive, compliance-preserving).

## Architecture (reference)

```
                       docker compose (single host)
┌────────────────────────────────────────────────────────────────────────┐
│  app:api (FastAPI, long-running)        app:cli (one-shot, run --rm)     │
│   ├─ POST /ask  → tools/ask.py           profile_analyst.py --stage 1..8 │
│   ├─ POST /rag  → tools/rag.py           profile_analyst.py erase | gc   │
│   └─ GET  /healthz                            │                          │
│        │  (SAME image; ENTRYPOINT branches: api | <cli args>)            │
│        └──────────────┬──────────────┬────────┴───────────┐             │
│                       ▼              ▼                    ▼             │
│                  ┌────────┐     ┌─────────┐          ┌─────────┐         │
│                  │ neo4j  │     │ ollama  │          │ mlflow  │         │
│                  │ 5.13+  │     │ (GPU)   │          │ server  │         │
│                  └───┬────┘     └────┬────┘          └────┬────┘         │
│              neo4j_data        ollama_models       ┌──────┴──────┐       │
│                              (ollama-pull init)    ▼             ▼       │
│                                              ┌──────────┐  ┌─────────┐   │
│                                              │ postgres │  │  minio  │   │
│                                              └──────────┘  └─────────┘   │
│  host bind-mount:  ./projects ⇄ /app/projects  (artifacts, erase, gc)   │
└────────────────────────────────────────────────────────────────────────┘
```

Key invariant: **one image, two run modes**; secrets injected at runtime (never baked);
`projects/` on a host bind mount so artifacts + GDPR Art.17 `erase`/`gc` stay durable and
inspectable; in-network service URIs use compose service names, not `localhost`.

## Implementation tracks (dependency-ordered)

### Track A — Pipeline image (foundation)

Build the single multi-stage image both run modes share (spec §4.2).

- `Dockerfile`: stage `builder` (`python:3.11-slim`, build deps, `pip install .` with core
  deps + `fastapi` + `uvicorn[standard]`; optional `[uil]`/`[rag]` extras behind build-args,
  default off) → stage `runtime` (`python:3.11-slim`, copy venv + source, non-root `appuser`
  UID 10001, `WORKDIR /app`, `VOLUME /app/projects`).
- `docker/entrypoint.sh`: branch on first arg — `api` → `uvicorn api.main:app --host 0.0.0.0
  --port 8000`; anything else → `python profile_analyst.py "$@"`.
- `.dockerignore`: exclude `projects/`, `.git`, test caches, `.env`.
- Add `fastapi` + `uvicorn[standard]` to `pyproject.toml` (no other dep changes).

**Exit:** `docker build` succeeds; `docker run <img> --handle sample --stage 1` runs the CLI
in-container as UID 10001 (non-root); the same image with `api` arg boots uvicorn.

---

### Track B — Read-only query API (`api/`) (depends on A)

The only net-new code (spec §4.3). Thin FastAPI surface; no analytics, no new safety logic.

- `api/models.py`: pydantic `AskRequest{question, handle?}`, `RagRequest{question, handle?,
  modes?}`, and response models wrapping the existing tool outputs (answer + manifest path).
- `api/deps.py`: shared Neo4j driver + Ollama client lifecycle (FastAPI startup/shutdown).
- `api/main.py`: `POST /ask` → call existing `tools/ask.py` entrypoint (inherits 0003 S1–S6 +
  read-only txn); `POST /rag` → call existing `tools/rag.py` entrypoint (inherits 0005
  fusion/safety); `GET /healthz` → 200 only when Neo4j + Ollama reachable; call
  `init_tracing()` once at startup when `OBSERVABILITY_ENABLED=true` (0006 §6.1).

**Exit:** `uvicorn api.main:app` serves all three routes; `/ask` and `/rag` return the same
answer + manifest the CLI produces; a mutation-y `/ask` question is rejected by 0003's gates;
`/healthz` flips to non-200 when a dependency is down.

---

### Track C — Backing services + config (parallel with A/B)

Define every non-app service and the single config wiring point (spec §4.1, §6, §7).

- `docker/mlflow.Dockerfile`: mini-image = `mlflow` + `psycopg2-binary` + `boto3`, pinned
  (0006 §14 deps) — resolves OQ1 default (custom mini-image).
- `.env.example` (committed; secrets empty, safe non-secret defaults): every 0001–0006 var
  (§7) — `LLM_BACKEND`, `ANTHROPIC_API_KEY`, `NEO4J_*`, `OLLAMA_*`, `OLLAMA_PULL_MODELS`,
  `RAG_*`, `MLFLOW_*`, Postgres/MinIO creds. In-network URIs use service names.
- Service definitions (drafted here, assembled in D): `neo4j:5.13-community` (vol
  `neo4j_data`/`neo4j_logs`, healthcheck `cypher-shell "RETURN 1"`); `ollama/ollama` with
  NVIDIA `deploy.reservations.devices` (vol `ollama_models`, healthcheck `/api/tags`);
  `ollama-pull` init (`restart:"no"`, pulls `OLLAMA_PULL_MODELS`, exits 0); `mlflow`
  (healthcheck `/health`); `postgres:16` (vol `mlflow_pg`, `pg_isready`); `minio/minio`
  (vol `minio_data`, `/minio/health/live`).

**Exit:** `docker compose up neo4j ollama mlflow postgres minio` brings all five backing
services to healthy and the `ollama-pull` init service exits 0 with the default models present.

---

### Track D — Compose topology & wiring (depends on A, B, C)

Assemble the full topology and the operator UX (spec §4.1, §5, §6, §9).

- `compose.yaml`: `app-api` service (built image, `api` command, `./projects` bind mount,
  published `API_PORT`, healthcheck `GET /healthz`); `app-cli` profile/one-shot definition
  (same image, run via `docker compose run --rm`). All backing services from Track C.
- Env wiring: map `.env` into every service; `NEO4J_URI=bolt://neo4j:7687`,
  `OLLAMA_HOST=http://ollama:11434`, `MLFLOW_TRACKING_URI=http://mlflow:5000`.
- `depends_on` + `condition: service_healthy`: `postgres`/`minio` → `mlflow`; `neo4j` +
  `ollama` (+ `mlflow` when observability on) → `app-api`; `ollama` → `ollama-pull`.
- `compose.gpu.yaml`: optional GPU tuning/override documented for lighter-VRAM hosts.
- `Makefile` targets: `up`, `down`, `pull-models`, `app ARGS="…"`, `api-logs`.

**Exit:** `docker compose up -d` brings the whole stack (incl. `app-api`) to healthy with
`ollama-pull` exited 0 (A1); `docker compose config` shows the nvidia reservation on `ollama`
(A8); startup ordering holds.

---

### Track E — Acceptance verification & docs (depends on D)

Prove the spec's A1–A12 and document operator setup.

- Smoke/integration checks (scripted or documented runbook; gated where a GPU/services are
  needed): CLI parity producing schema-valid `01..08` + `report.md` on the host mount (A3);
  `--stage 7` populating composed Neo4j + valid manifest (A4); `/ask` grounded answer +
  manifest, mutation rejected (A5); `/rag` answer + citations + manifest, zero-result honesty
  (A6); `docker history` shows no baked secrets (A7); readiness recovery when Neo4j bounces
  (A9); MLflow trace on/off behavior (A10); host erasure via `run --rm app erase` (A11).
- `README` / deployment doc: NVIDIA Container Toolkit prerequisite + WSL2 CUDA note (§6),
  `.env` secret generation, lighter-model overrides, `down -v` full wipe (C3).
- `make validate` green with the accepted `metadata.yml` (A12) — no schema changes.

**Exit:** A1–A12 demonstrably pass (or are scripted/documented where they need live GPU);
`make validate` and `make test` green.

---

**Dependency graph:** A → B; C ∥ (A,B); {A, B, C} → D → E.

## Risks

- **GPU availability (esp. WSL2).** The spec requires NVIDIA GPU; the dev host is WSL2.
  *Mitigation:* GPU is a documented host prerequisite (not managed, mirrors 0003 N6);
  `compose.gpu.yaml` + lighter-model env overrides give a CPU/low-VRAM path for dev, while the
  reservation stays in the main compose (A8 checks `docker compose config`, not live GPU).
- **Cold-start model pull (~20 GB).** `ollama-pull` downloads large models at first `up`.
  *Mitigation:* pull into a named volume once (OQ3 default, runtime pull not baked); document
  the cost; `OLLAMA_PULL_MODELS` overridable to a lighter set.
- **Secrets in image.** A baked key would be a compliance failure. *Mitigation:* `.env` +
  runtime env injection only; `.dockerignore` excludes `.env`; A7 greps `docker history`.
- **Readiness flakiness.** A slow Neo4j/Ollama could crash-loop `app-api`. *Mitigation:*
  healthcheck-gated `depends_on`; `/healthz` reflects dependency reachability so the API stays
  unhealthy (not crashed) until deps recover (A9).
- **Compose drift from prior-spec config.** Env vars are defined across six specs.
  *Mitigation:* `.env.example` is the single wiring point; service-name URIs override the
  bare-metal `localhost` defaults explicitly (§7).

## Open implementation questions

- **OQ1** MLflow image: upstream + pip layer vs custom mini-Dockerfile. *Default:* custom
  `docker/mlflow.Dockerfile` (explicit pinned deps; matches 0006 §14).
- **OQ2** Serve batch stages via API (`POST /run`) vs `docker compose run` one-shots only.
  *Default:* one-shots only — API stays read-only (N6).
- **OQ3** Ollama models pulled at runtime into a volume vs baked into the image.
  *Default:* runtime pull via the `ollama-pull` init service.
- **OQ4** Publish tagged images to a registry vs local build only. *Default:* local build
  only; registry/CI is Future Work (N5).
- **OQ5** Per-service memory/CPU limits (esp. Neo4j heap) in compose vs documented only.
  *Default:* document recommended values in `.env.example`; no hard caps in v1.
