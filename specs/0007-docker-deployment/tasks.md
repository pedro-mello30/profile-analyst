# Tasks 0007 — Docker Deployment & Service Orchestration

From `plan.md`. Land track-by-track; each task is independently verifiable. Tracks A, B, C
are largely parallel; D integrates them; E verifies.

## Track A — Pipeline image

- [ ] T1 Add `fastapi` + `uvicorn[standard]` to `pyproject.toml` dependencies (core); keep
      `[uil]`/`[rag]` as optional extras. No other dependency changes.
- [ ] T2 Write `Dockerfile` stage `builder` (`python:3.11-slim`): install build deps,
      `pip install .` into a venv; expose `INSTALL_EXTRAS` build-arg (default empty).
- [ ] T3 Write `Dockerfile` stage `runtime` (`python:3.11-slim`): copy venv + app source,
      create non-root `appuser` (UID 10001), `WORKDIR /app`, `VOLUME /app/projects`,
      `ENTRYPOINT ["docker/entrypoint.sh"]`.
- [ ] T4 Write `docker/entrypoint.sh`: if `$1 == api` → `exec uvicorn api.main:app --host
      0.0.0.0 --port ${API_PORT:-8000}`; else → `exec python profile_analyst.py "$@"`. Make
      it executable; do not `chown` host mounts.
- [ ] T5 Write `.dockerignore` excluding `projects/`, `.git`, `__pycache__`, `.pytest_cache`,
      `.env`, `*.md` build noise.

## Track B — Read-only query API (`api/`)

- [ ] T6 `api/models.py`: pydantic `AskRequest{question: str, handle: str | None}`,
      `RagRequest{question: str, handle: str | None, modes: list[str] | None}`, and response
      models returning `answer` + `manifest_path` (+ `citations` for RAG).
- [ ] T7 `api/deps.py`: app-scoped Neo4j driver + Ollama client created on FastAPI startup,
      closed on shutdown; a `check_dependencies()` helper used by `/healthz`.
- [ ] T8 `api/main.py` `POST /ask`: call the existing `tools/ask.py` entrypoint function and
      return its answer + manifest. No new Cypher/safety — inherits 0003 S1–S6 + read-only txn.
- [ ] T9 `api/main.py` `POST /rag`: call the existing `tools/rag.py` entrypoint function and
      return answer + `citations[]` + manifest. Inherits 0005 fusion/safety unchanged.
- [ ] T10 `api/main.py` `GET /healthz`: return 200 only when `check_dependencies()` confirms
      Neo4j and Ollama reachable; else 503.
- [ ] T11 `api/main.py` startup: call `observability.init_tracing()` once when
      `OBSERVABILITY_ENABLED=true` (0006 §6.1); request handlers are the `influencer_rag` CHAIN
      entrypoint (wiring only, no new spans defined here).

## Track C — Backing services + config

- [ ] T12 `docker/mlflow.Dockerfile`: `mlflow` + `psycopg2-binary` + `boto3`, pinned versions
      (0006 §14); entrypoint runs `mlflow server` with backend-store + artifacts-destination
      from env.
- [ ] T13 `.env.example` (committed): all 0001–0006 vars from spec §7, secrets left empty,
      safe non-secret defaults; in-network URIs use service names (`neo4j`, `ollama`, `mlflow`,
      `postgres`, `minio`).
- [ ] T14 Draft `neo4j` service: `neo4j:5.13-community`, `NEO4J_AUTH`, vols `neo4j_data` +
      `neo4j_logs`, healthcheck `cypher-shell "RETURN 1"`. (No GDS plugin — N7.)
- [ ] T15 Draft `ollama` service: `ollama/ollama` (pin digest), `deploy.resources.reservations.
      devices` nvidia/all/gpu, vol `ollama_models`, `OLLAMA_KEEP_ALIVE`, healthcheck `/api/tags`.
- [ ] T16 Draft `ollama-pull` init service: same image, `restart:"no"`, command pulls each of
      `OLLAMA_PULL_MODELS` then exits 0; shares `ollama_models`.
- [ ] T17 Draft `postgres:16` (vol `mlflow_pg`, `pg_isready` healthcheck) and `minio/minio`
      (vol `minio_data`, `/minio/health/live` healthcheck) services for the MLflow backend.

## Track D — Compose topology & wiring

- [ ] T18 `compose.yaml`: assemble all backing services (C) + `app-api` (built image, `api`
      command, `./projects` bind mount, publish `${API_PORT}`, healthcheck `GET /healthz`).
- [ ] T19 `compose.yaml`: `app-cli` one-shot definition (same image, run via `docker compose
      run --rm app …`), passing through `--allow-noncompliant` as an arg (never a default).
- [ ] T20 `compose.yaml`: env wiring from `.env` into every service; set `NEO4J_URI`,
      `OLLAMA_HOST`, `MLFLOW_TRACKING_URI` to service-name URIs.
- [ ] T21 `compose.yaml`: `depends_on` with `condition: service_healthy` — postgres/minio →
      mlflow; neo4j + ollama (+ mlflow when `OBSERVABILITY_ENABLED=true`) → app-api; ollama →
      ollama-pull.
- [ ] T22 `compose.yaml`: declare named volumes `neo4j_data`, `neo4j_logs`, `ollama_models`,
      `mlflow_pg`, `minio_data`.
- [ ] T23 `compose.gpu.yaml`: optional GPU/override file documented for lighter-VRAM hosts.
- [ ] T24 `Makefile`: add `up`, `down`, `pull-models`, `app ARGS="…"`, `api-logs` targets.

## Track E — Acceptance verification & docs

- [ ] T25 Verify A1/A8: `docker compose up -d` → all services healthy, `ollama-pull` exited 0;
      `docker compose config` shows the nvidia reservation on `ollama`.
- [ ] T26 Verify A2: running `app-api` process is UID 10001 (`docker exec app-api id -u`).
- [ ] T27 Verify A3/A4/A11: `docker compose run --rm app --handle sample --stage all` →
      schema-valid `01..08` + `report.md` on host mount; `--stage 7` populates composed Neo4j +
      valid manifest; `erase --handle sample` removes `projects/sample/` on the host.
- [ ] T28 Verify A5/A6: `POST /ask` grounded answer + manifest, injected mutation rejected;
      `POST /rag` answer + `citations[]` + manifest after `--stage 8`, zero-result honesty.
- [ ] T29 Verify A7/A9/A10: `docker history` shows no baked secrets; bouncing `neo4j` flips
      `/healthz` then recovers without crash loop; `/rag` produces an MLflow trace when on and
      none when off.
- [ ] T30 Write deployment doc / README section: NVIDIA Container Toolkit + WSL2 CUDA note,
      `.env` secret generation, lighter-model overrides, `down -v` full wipe.
- [ ] T31 Verify A12: `make validate` green with accepted `metadata.yml`; `make test` green.

**Total: ~31 tasks** across 5 tracks.

## Out of scope (do not include in this PR)

- Pipeline-logic, schema, or analytics changes (N1/N2) — this spec only packages/orchestrates.
- A write path or `POST /run` from the API (N6, OQ2) — batch stays `docker compose run`.
- Neo4j GDS plugin in the image (N7) — added when spec 0004 ships.
- CI/CD, image registry publishing, SBOM (N5, OQ4) — Future Work.
- Kubernetes/Helm, multi-host orchestration (N3) — Future Work.
- Docker secrets / vault integration — Future Work (§7 hardening).
