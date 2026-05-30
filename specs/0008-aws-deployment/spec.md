# Spec 0008 — AWS Deployment (ECS Fargate)

**Status:** draft
**Depends on:** `0007-docker-deployment` (the images + compose topology this spec lifts to AWS) ·
`0001-social-media-associations-profile` (the pipeline that runs; Art.17 erase/gc) ·
`0002-neo4j-graph-persistence` (Neo4j service) · `0003-ollama-llm-graph-query` (Ollama backend +
`/ask`) · `0005-hybrid-rag-retrieval` (`/rag`) · `0006-mlflow-observability` (MLflow + Postgres +
artifact store)
**Owner:** Pedro Mello
**Created:** 2026-05-30
**Source of truth:** this document. Read before implementing anything under `deploy/aws/`,
`infra/`, or the AWS task definitions.

---

## 1. Problem Statement

Spec 0007 packages the whole platform into one image + a `docker compose` topology, but its scope
is explicitly **single-host** (0007 N3) with **local datastores** (0007 N4), `.env` secret
injection (0007 §7), and a **GPU-required** Ollama service (0007 §6). That is correct for a dev
box; it does not give us a durable, multi-AZ, secret-managed cloud deployment.

Three concrete gaps block running this on AWS:

- **No managed runtime.** A single EC2 box running `docker compose` is a pet, not cattle: no
  health-based replacement, no rolling deploys, no multi-AZ durability, manual scaling. The batch
  pipeline (handle → dossier) and the read-only query API have different lifecycles and should
  scale independently.
- **GPU + Fargate are incompatible.** 0007's Ollama service reserves an NVIDIA GPU. **AWS Fargate
  has no GPU support.** A cloud deployment must either (a) default Stage 3 / `/ask` to the
  **Anthropic API** backend (no GPU needed), or (b) run Ollama on a separate **EC2 GPU capacity
  provider** — not on Fargate. This spec makes (a) the cloud default and (b) an opt-in profile.
- **Local state doesn't survive cattle.** Container-local `projects/`, `neo4j_data`, the MLflow
  Postgres, and the MinIO artifact bucket vanish when a task is replaced. On AWS these must move to
  **durable, shared, multi-AZ** stores: **EFS** for the `projects/` tree and Neo4j data, **RDS**
  for the MLflow backend, **S3** for the MLflow artifact store (replacing MinIO).

This spec defines an **ECS Fargate deployment**: the 0007 images run as ECS services behind an ALB,
state moves to EFS/RDS/S3, secrets move to **AWS Secrets Manager / SSM Parameter Store**, and a
**batch run is triggered asynchronously** (the always-on API enqueues a handle; an ECS worker task
runs the pipeline). It changes **no pipeline logic** — it is an infrastructure + thin
enqueue-endpoint layer over what 0001–0007 already define.

## 2. Goals

- **G1. ECS Fargate topology.** Run the 0007 image as ECS Fargate services (`api`, `neo4j`,
  `mlflow`) behind an internet-facing **ALB**, across ≥2 AZs in private subnets, defined as
  infrastructure-as-code (Terraform).
- **G2. Always-on read API.** The 0007 FastAPI service (`/ask`, `/rag`, `/healthz`) runs as a
  long-lived ECS service, fronted by the ALB with target-group health checks on `/healthz`.
- **G3. Async batch runs.** A new `POST /runs {handle, stages?}` enqueues a job to **SQS**; an ECS
  **worker** task (same image, CLI entrypoint, launched via `ECS RunTask`) consumes the message,
  runs `profile_analyst.py --handle <h> --stage <…>`, writes artifacts to the shared EFS tree, and
  exits. `GET /runs/{id}` reports status. This is the **only net-new application code**.
- **G4. Durable shared state.** `projects/` and Neo4j data live on **EFS** (multi-AZ, shared by
  api + worker + neo4j tasks); MLflow metadata on **RDS PostgreSQL**; MLflow artifacts on **S3**
  (MinIO from 0007 is dropped — S3 is the native artifact store).
- **G5. Managed secrets.** Every secret from 0007 §7 (`ANTHROPIC_API_KEY`, `NEO4J_PASSWORD`,
  RDS creds, …) is stored in **Secrets Manager**, injected into tasks via the ECS task-definition
  `secrets` block at runtime — never baked into the image, never in plaintext env (carries 0007 C1).
- **G6. Anthropic-default backend; optional GPU profile.** `LLM_BACKEND=anthropic` is the cloud
  default so the core stack is **all-Fargate** (no GPU). An **opt-in** `ollama` profile runs Ollama
  on an **ECS EC2 GPU capacity provider** (`g5`/`g4dn`) for local-only-egress deployments.
- **G7. Compliance preserved end-to-end.** Art.17 erase/`gc` (0001), the ToS gate
  (`--allow-noncompliant`), Art.9/Art.22 lineage, and local-egress posture all carry over; erasure
  operates on the durable EFS tree, and `aws s3`/RDS deletes cover the graph/observability copies.

## 3. Non-Goals

- **N1. No pipeline-logic changes.** Stages 1–8, scoring, compliance gates, CLI flags, `/ask`,
  `/rag` are untouched. Net-new code is limited to the `/runs` enqueue endpoint + the SQS worker
  loop (G3), both delegating to existing functions.
- **N2. No Kubernetes / EKS.** ECS Fargate only (the question selected ECS Fargate). EKS is
  Future Work, as in 0007 N3's spirit.
- **N3. No new analytics or query path.** `/ask` and `/rag` are surfaced exactly as 0007 does,
  inheriting 0003/0005 safety gates; `/runs` adds orchestration, not analytics.
- **N4. No GPU on Fargate.** The core stack is CPU-only with `LLM_BACKEND=anthropic`. GPU is the
  opt-in EC2 profile (G6), not the default.
- **N5. No CI/CD in this spec.** Building/pushing images to **ECR** and a deploy pipeline are
  assumed to be driven manually (`docker build` + `docker push`) for v1; GitHub Actions / CodePipeline is Future Work (mirrors 0007 N5).
- **N6. No public Neo4j/Ollama/MLflow.** Only the ALB (→ api) is internet-facing. Neo4j, Ollama,
  RDS, and MLflow are private (security groups + private subnets); MLflow UI is reached via the ALB
  on an authenticated path or not at all (OQ4).
- **N7. No multi-region / DR.** Single region, multi-AZ. Cross-region replication and DR runbooks
  are Future Work.
- **N8. No autoscaling tuning.** Services run at a fixed desired-count for v1; target-tracking
  autoscaling policies are documented but not required to pass acceptance (OQ5).

## 4. Architecture & Topology

```
                                  AWS region (single), ≥2 AZs
┌───────────────────────────────────────────────────────────────────────────────────┐
│  Internet                                                                            │
│     │                                                                                │
│     ▼                                                                                │
│  ┌────────────┐   public subnets                                                     │
│  │   ALB      │   (HTTPS :443, ACM cert)                                             │
│  └─────┬──────┘                                                                      │
│        │  target group → /healthz                                                    │
│        ▼                  private subnets (no public IPs; NAT egress for Anthropic)  │
│  ┌──────────────┐    POST /runs      ┌──────────┐   RunTask    ┌──────────────────┐  │
│  │ ecs: api     │ ─────enqueue─────▶ │  SQS     │ ───────────▶ │ ecs: worker      │  │
│  │ (Fargate)    │                    │  jobs    │              │ (Fargate, CLI    │  │
│  │ /ask /rag    │ ◀── GET /runs/{id} │  queue   │              │  entrypoint)     │  │
│  │ /healthz     │                    └──────────┘              │ profile_analyst  │  │
│  └──┬───────┬───┘                         │ DLQ                └────────┬─────────┘  │
│     │       │                                                           │            │
│     │       └──────────────┬──────────────────────────────────────────┘            │
│     ▼                      ▼                          ▼                              │
│  ┌────────┐          ┌──────────┐              ┌────────────┐    (opt-in profile)    │
│  │ neo4j  │          │  EFS      │              │  mlflow    │   ┌────────────────┐   │
│  │Fargate │──data──▶ │ projects/ │◀──artifacts─ │ (Fargate)  │   │ ollama (EC2    │   │
│  │        │          │ + neo4j   │              └─────┬──────┘   │  GPU capacity  │   │
│  └────────┘          └──────────┘                     │          │  provider)     │   │
│                                              ┌────────┴────────┐ └────────────────┘   │
│                                              ▼                 ▼                      │
│                                        ┌──────────┐      ┌──────────┐                 │
│                                        │ RDS      │      │  S3      │                 │
│                                        │ Postgres │      │ mlflow   │                 │
│                                        │ (mlflow) │      │ artifacts│                 │
│                                        └──────────┘      └──────────┘                 │
│                                                                                       │
│  Secrets Manager / SSM ── injected into every task definition (G5)                    │
│  CloudWatch Logs ── all task stdout/stderr; container insights                        │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 ECS services & tasks

| Logical | Launch type | Image | Role | State | Health |
|---------|-------------|-------|------|-------|--------|
| `api` | Fargate (svc, desired ≥2) | 0007 image, `api` entrypoint | `/ask` `/rag` `/runs` `/healthz` behind ALB | EFS `projects/` (ro+rw) | ALB → `GET /healthz` |
| `worker` | Fargate (RunTask, on demand) | 0007 image, CLI entrypoint | consumes SQS, runs `--stage …` | EFS `projects/` (rw) | n/a (one-shot) |
| `neo4j` | Fargate (svc, desired 1) | `neo4j:5.13-community` | graph store + indexes | EFS `neo4j_data`, `neo4j_logs` | `cypher-shell "RETURN 1"` |
| `mlflow` | Fargate (svc, desired 1) | 0007 `docker/mlflow.Dockerfile` | tracking server | RDS (backend) + S3 (artifacts) | `GET /health` |
| `ollama` | **EC2** GPU capacity provider (opt-in) | `ollama/ollama` | local LLM + embeddings | EBS/EFS `ollama_models` | `GET /api/tags` |
| `postgres` | **RDS** (managed, not a task) | RDS PostgreSQL 16 | MLflow metadata | RDS storage (multi-AZ) | RDS health |

- **Service discovery:** AWS Cloud Map private DNS namespace (e.g. `*.analyst.local`) gives the
  stable names the prior specs expect — `neo4j`, `ollama`, `mlflow` — so `NEO4J_URI=bolt://neo4j.analyst.local:7687`
  etc. resolve inside the VPC (replaces the compose service-name DNS of 0007 §7).
- **Same image, two entrypoints:** `api` and `worker` are the **same ECR image** (0007 G2), branching
  via `docker/entrypoint.sh` (0007 §4.2): `api` → uvicorn; default → `python profile_analyst.py "$@"`.

### 4.2 The worker & `/runs` (net-new code, §G3)

```
api/
├── runs.py        # POST /runs {handle, stages?} → validate, enqueue SQS msg, return {run_id, status:queued}
│                  # GET  /runs/{id}             → read status from EFS marker / DynamoDB (OQ3)
└── worker.py      # SQS long-poll loop: receive → run pipeline for handle → write status → delete msg
```

- `POST /runs` validates `handle` + optional `stages` (defaults `all`), generates a `run_id` (UUID),
  writes a `queued` status marker, and sends one SQS message. **It does not run the pipeline in the
  API process** (keeps `api` light and the API still effectively read-only for analytics — the
  pipeline runs in the isolated worker, honoring 0007 N6's spirit while satisfying the chosen
  enqueue model).
- `worker.py` is the container command for the `worker` task: long-poll SQS, on a message run
  `profile_analyst.main(handle=…, stages=…)`, update the status marker (`running`→`succeeded`/`failed`),
  then delete the SQS message (visibility-timeout-bounded). Poison messages → **DLQ** after N
  receives.
- **Worker invocation:** v1 uses **ECS RunTask** launched per message (simplest, scales to zero).
  An always-on worker service polling SQS is the alternative (OQ2); default is RunTask-per-batch via
  an SQS→EventBridge Pipe or the api enqueuing + a small launcher (OQ2 decides the trigger).

### 4.3 Persistence mapping (0007 → AWS)

| 0007 (compose) | AWS (this spec) | Why |
|----------------|-----------------|-----|
| bind mount `./projects` | **EFS** access point, mounted at `/app/projects` on api + worker | shared, multi-AZ, survives task replacement; Art.17 erase operates here |
| `neo4j_data`, `neo4j_logs` volumes | **EFS** access points mounted into the neo4j task | durable graph store across task restarts |
| `mlflow_pg` (Postgres volume) | **RDS PostgreSQL 16** (multi-AZ) | managed backend store; no DB to babysit |
| `minio_data` (MinIO) | **S3 bucket** `s3://<acct>-analyst-mlflow/` | native artifact store; MinIO dropped (G4) |
| `ollama_models` volume | EBS/EFS on the EC2 GPU host (opt-in profile only) | only present when the `ollama` profile is enabled |

## 5. Configuration & Secrets (0007 §7 → AWS)

The `.env` of 0007 becomes **task-definition env + `secrets`**. Non-secret values are plain
`environment`; secrets are `secrets[].valueFrom` ARNs resolved at task start (G5).

```
# --- non-secret env (task definition `environment`) ---
LLM_BACKEND=anthropic                         # cloud default — no GPU (G6); set `ollama` only with the GPU profile
ALLOW_NONCOMPLIANT=false                       # 0001 ToS gate (never defaulted true)
API_PORT=8000
NEO4J_URI=bolt://neo4j.analyst.local:7687      # Cloud Map private DNS
NEO4J_USER=neo4j
NEO4J_DATABASE=neo4j
OLLAMA_HOST=http://ollama.analyst.local:11434  # only resolvable when the ollama profile is up
OLLAMA_CYPHER_MODEL=qwen2.5-coder:32b
OLLAMA_EMBED_MODEL=nomic-embed-text
OBSERVABILITY_ENABLED=true
MLFLOW_TRACKING_URI=http://mlflow.analyst.local:5000
MLFLOW_ARTIFACTS_DESTINATION=s3://<acct>-analyst-mlflow/
RUNS_QUEUE_URL=https://sqs.<region>.amazonaws.com/<acct>/analyst-runs
PROJECTS_DIR=/app/projects                      # EFS mount target

# --- secrets (task definition `secrets`, valueFrom = Secrets Manager / SSM ARN) ---
ANTHROPIC_API_KEY        → arn:aws:secretsmanager:…:analyst/anthropic_api_key      # required when LLM_BACKEND=anthropic
NEO4J_PASSWORD           → arn:aws:secretsmanager:…:analyst/neo4j_password
MLFLOW_BACKEND_STORE_URI → arn:aws:secretsmanager:…:analyst/mlflow_db_uri          # postgresql://…@<rds-endpoint>:5432/mlflow
```

- **Egress:** Fargate tasks run in private subnets with a **NAT gateway** for the single intentional
  egress — the Anthropic API when `LLM_BACKEND=anthropic` (0001). With the `ollama` profile and
  `LLM_BACKEND=ollama`, no creator data leaves the VPC (carries 0007 C4); S3/RDS/Secrets Manager are
  reached via **VPC endpoints** to keep that traffic off the public internet.
- **IAM least privilege:** the api task role may `sqs:SendMessage` + read status; the worker task
  role may `sqs:ReceiveMessage/DeleteMessage`, read EFS, `s3:*` on the mlflow bucket, and read the
  three secrets. Neo4j/mlflow task roles get only what they need.

## 6. Compliance (carried from 0001 §9 / 0002 §7 / 0007 §8)

- **C1. No baked secrets.** Image is identical to 0007 (no secrets in layers, 0007 A7); secrets
  arrive only via the ECS `secrets` block from Secrets Manager (G5). Verified by A7 below.
- **C2. Art.17 erasure on durable state.** `erase --handle <h>` runs as a worker task
  (`ECS RunTask … erase --handle <h>`) and deletes `projects/<h>/` on the **EFS** tree; a companion
  step removes that creator's subgraph from Neo4j (0002 future-work erasure path) and any MLflow
  artifacts in S3. Erasure is real and durable, not container-local.
- **C3. Service state durable + wipeable.** EFS (projects, neo4j), RDS (mlflow meta), S3 (mlflow
  artifacts) survive restarts; a documented teardown (`terraform destroy` + bucket empty) is the
  full-wipe equivalent of 0007's `compose down -v`.
- **C4. Local-egress option preserved.** The `ollama` GPU profile + `LLM_BACKEND=ollama` keeps all
  creator data inside the VPC; only the operator-chosen Anthropic backend egresses (via NAT), exactly
  as 0001/0007 intend.
- **C5. Art.9 / Art.22 unchanged.** `/ask` `/rag` surface 0003/0005 answers verbatim; MLflow
  redaction (0006) still applies. No new analytics path touches lineage.
- **C6. ToS gate honored.** `--allow-noncompliant` is passed only as an explicit arg on a worker
  RunTask / `/runs` body flag; it is never a task-definition default (stays `false`).

## 7. Files Added

```
deploy/aws/
├── README.md                  # deploy runbook: bootstrap, push to ECR, terraform apply, smoke test
├── terraform/
│   ├── main.tf                # provider, backend (S3 + DynamoDB lock)
│   ├── network.tf             # VPC, public/private subnets (≥2 AZ), NAT, VPC endpoints
│   ├── ecs.tf                 # cluster, capacity providers (Fargate + optional EC2 GPU)
│   ├── services.tf            # api / neo4j / mlflow services + worker task def
│   ├── alb.tf                 # ALB, listener (ACM 443), target group → /healthz
│   ├── efs.tf                 # EFS + access points (projects, neo4j_data, neo4j_logs)
│   ├── rds.tf                 # RDS PostgreSQL (mlflow backend)
│   ├── s3.tf                  # mlflow artifact bucket (+ TF state bucket note)
│   ├── sqs.tf                 # runs queue + DLQ
│   ├── secrets.tf             # Secrets Manager entries (values supplied out-of-band)
│   ├── iam.tf                 # task roles + execution role (least privilege, §5)
│   ├── observability.tf       # CloudWatch log groups, Container Insights
│   ├── ollama-gpu.tf          # opt-in: EC2 GPU capacity provider + ollama service (count 0 default)
│   ├── variables.tf
│   └── outputs.tf             # alb_dns_name, ecr_repo_url, queue_url
api/
├── runs.py                    # POST /runs, GET /runs/{id}   (net-new)
└── worker.py                  # SQS consumer loop               (net-new)
```

`Makefile` gains AWS targets (consistent with the 0007 `make` UX):

```
make aws-ecr-push       # docker build + tag + push the 0007 image to ECR
make aws-deploy         # terraform -chdir=deploy/aws/terraform apply
make aws-run HANDLE=sample STAGES=all   # aws ecs run-task … worker (one batch)
make aws-smoke          # curl https://<alb>/healthz ; POST /runs sample ; poll GET /runs/{id}
make aws-destroy        # terraform destroy (+ documented bucket/efs cleanup)
```

## 8. Acceptance Criteria

- **A1. Stack provisions.** `terraform apply` creates VPC, ALB, ECS cluster, `api`/`neo4j`/`mlflow`
  services (Fargate), EFS, RDS, S3, SQS, secrets, and IAM with no manual steps beyond supplying
  secret values; `terraform plan` is clean on re-run (idempotent).
- **A2. API reachable & healthy.** `GET https://<alb_dns_name>/healthz` returns 200; the ALB target
  group reports the `api` tasks healthy across ≥2 AZs.
- **A3. Async batch run.** `POST /runs {"handle":"sample"}` returns `{run_id, status:"queued"}`; a
  worker task runs and produces `projects/sample/01..08` + `report.md` on the **EFS** tree, each
  schema-valid (0001 A2 holds on AWS); `GET /runs/{run_id}` ends at `succeeded`.
- **A4. Stage 7 against cloud Neo4j.** The worker's Stage 7 populates the `neo4j` ECS task
  (Creator/Media/Signal/Score) and writes `07-load-manifest.json` (0002 A1 holds against cloud Neo4j).
- **A5. Ask/RAG via ALB.** `POST /ask` returns a grounded answer; an injected mutation question is
  rejected (0003 A1/A2). With Stage 8 run, `POST /rag` returns an answer + `citations[]` (0005 A8).
- **A6. Managed secrets, none baked.** `docker history` on the ECR image shows no secret values
  (0007 A7); tasks start only after Secrets Manager resolves `ANTHROPIC_API_KEY`/`NEO4J_PASSWORD`/
  RDS URI; removing the secret makes the task fail to start (proving runtime injection).
- **A7. Durable state survives replacement.** Killing the `api` task (forced new deployment) and the
  `neo4j` task leaves `projects/` artifacts and the loaded graph intact (EFS + restart), and MLflow
  history intact (RDS + S3).
- **A8. MLflow on RDS+S3.** With `OBSERVABILITY_ENABLED=true`, a `/rag` call writes a trace whose
  metadata lands in RDS and artifacts in the S3 bucket (0006 A1 holds with managed backends).
- **A9. Anthropic-default, no GPU.** The core stack runs entirely on Fargate with
  `LLM_BACKEND=anthropic` and **no** GPU capacity provider enabled; `/ask` works without Ollama.
- **A10. GPU profile opt-in.** Enabling the `ollama` profile provisions an EC2 GPU capacity provider;
  `ollama` becomes healthy and, with `LLM_BACKEND=ollama`, `/ask` answers with no NAT egress of
  creator data (VPC-only).
- **A11. Erasure on durable state.** `aws ecs run-task … erase --handle sample` removes
  `projects/sample/` on EFS and returns an erasure receipt (0001 Art.17 holds on AWS).
- **A12. Private by default.** Only the ALB is internet-facing; `neo4j`, `ollama`, `mlflow`, RDS have
  no public ingress (security-group + subnet audit); `make validate` passes with this `metadata.yml`.
- **A13. Poison-message safety.** A `/runs` job for an invalid handle ends `failed` and, after N
  receives, the SQS message lands in the DLQ without crash-looping the worker.

## 9. Open Questions

- **OQ1. IaC tool.** Terraform (assumed here) vs AWS CDK vs CloudFormation/Copilot. Default:
  **Terraform** (cloud-agnostic-ish, S3+DynamoDB remote state). Confirm before scaffolding `infra/`.
- **OQ2. Worker trigger.** `ECS RunTask`-per-message (scales to zero, slower cold start) vs an
  always-on worker **service** long-polling SQS (faster, costs idle). Default: RunTask-per-batch via
  an EventBridge Pipe (SQS→ECS), revisit if cold-start latency hurts.
- **OQ3. Run-status store.** Where `GET /runs/{id}` reads status from: a JSON marker on EFS
  (simplest, no new service) vs **DynamoDB** (queryable, TTL'd). Default: EFS marker for v1;
  DynamoDB if status querying grows.
- **OQ4. MLflow UI exposure.** Keep MLflow fully private (port-forward / bastion) vs an
  authenticated ALB path. Default: private only for v1 (N6); ALB path with auth is Future Work.
- **OQ5. Autoscaling.** Fixed desired-count (v1) vs target-tracking on ALB request count / SQS depth.
  Default: fixed counts; document scaling policies, don't gate acceptance (N8).
- **OQ6. Neo4j on Fargate vs Aura.** Self-managed Neo4j-on-Fargate+EFS (chosen, keeps 0002 posture)
  vs managed **Neo4j AuraDB**. Default: self-managed on Fargate; Aura is a Future-Work swap.

## 10. Future Work (out of scope here)

- **CI/CD:** GitHub Actions / CodePipeline to build, scan, push to ECR and `terraform apply` on merge
  (supersedes N5's manual push).
- **EKS / Helm** for teams standardizing on Kubernetes (supersedes the ECS-only N2).
- **Multi-region DR:** cross-region S3 replication, RDS read replica / snapshot copy, runbook (N7).
- **Autoscaling + cost controls:** SQS-depth-driven worker scaling, Fargate Spot for the worker,
  scheduled scale-to-zero of `neo4j`/`mlflow` in non-prod.
- **Managed swaps:** Neo4j AuraDB (OQ6), and — if the project later adds it — Bedrock as a
  same-VPC alternative to the Anthropic public API for Stage 3.
- **WAF + auth on the ALB** for the public `api`, and an authenticated MLflow UI path (OQ4).
- **Graph + observability erasure automation:** wrap C2's EFS+Neo4j+S3 deletes into one
  `erase --handle` worker command so Art.17 is a single auditable action on AWS.
