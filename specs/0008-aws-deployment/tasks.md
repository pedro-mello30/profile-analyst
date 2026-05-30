# Tasks 0008 — AWS Deployment (ECS Fargate)

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A, B can be done in parallel. C depends on A, B; D depends on A–C.

---

## Track A — AWS Infrastructure (Terraform IaC)

### Networking & foundational

- [ ] T1 Create `deploy/aws/terraform/main.tf` — provider (aws, region), backend (S3 + DynamoDB),
      required variables (region, env, app_name, desired_api_count, desired_neo4j_count).
- [ ] T2 Create `deploy/aws/terraform/variables.tf` — define all input variables with descriptions and
      defaults; include network CIDR ranges, instance types, database size, secret names.
- [ ] T3 Create `deploy/aws/terraform/network.tf` — VPC (10.0.0.0/16), ≥2 AZ public subnets, ≥2
      private subnets, NAT gateway (HA: one per AZ or single with route failover), Internet Gateway,
      route tables. All subnets tagged for ALB/ECS discovery.
- [ ] T4 Create VPC endpoints for S3 (gateway), Secrets Manager (interface), RDS (for private subnets).

### Compute & orchestration

- [ ] T5 Create `deploy/aws/terraform/ecs.tf` — ECS cluster (no capacity providers yet; added in T11),
      CloudWatch Container Insights enabled, cluster tags for resource discovery.
- [ ] T6 Create `deploy/aws/terraform/services.tf` — task definitions for api, neo4j, mlflow, worker.
      Each task definition: 0007 image URI (from ECR output), container name, port mappings, EFS/RDS
      mount config, log driver (CloudWatch), secrets (valueFrom), environment vars. Task roles with
      least-privilege IAM (separate for api, worker, mlflow, neo4j). Execution role with
      secretsmanager:GetSecretValue, logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents.

### Load balancing & service discovery

- [ ] T7 Create `deploy/aws/terraform/alb.tf` — ALB (internet-facing, ≥2 AZs), HTTPS listener (ACM
      certificate — user-supplied or auto-created), HTTP → HTTPS redirect. Target group for api service
      (port 8000), health check on GET /healthz (200 expected). Security group: ingress 443 from
      anywhere, 80 (redirect), egress all. Register api Fargate tasks as targets.
- [ ] T8 Create AWS Cloud Map private DNS namespace `analyst.local` and register services (neo4j,
      ollama, mlflow, postgres) so they resolve by hostname inside the VPC.

### Storage

- [ ] T9 Create `deploy/aws/terraform/efs.tf` — EFS (multi-AZ, gp2, bursting enabled). Create access
      points: `/projects` (mode 0755, owner 10001:10001), `/neo4j_data`, `/neo4j_logs`. Throughput
      mode: bursting. Mount targets in each private subnet.
- [ ] T10 Create `deploy/aws/terraform/rds.tf` — RDS PostgreSQL 16, multi-AZ (standby), 20 GB
       storage, db.t3.micro (or user-configurable), `mlflow` database pre-created, automated backups
       (7 days retention). Security group: ingress port 5432 from ECS subnet. Enhanced monitoring.
- [ ] T11 Create `deploy/aws/terraform/s3.tf` — S3 bucket `<acct>-analyst-mlflow`, versioning
       enabled, private ACL, server-side encryption (AES-256), lifecycle rule (delete old versions
       after 30 days). Separate bucket for Terraform state (versioning, MFA delete).

### Queues & async

- [ ] T12 Create `deploy/aws/terraform/sqs.tf` — SQS queue `analyst-runs` (standard queue,
       VisibilityTimeout 300s, MessageRetentionPeriod 1209600 = 14 days, ReceiveMessageWaitTimeSeconds
       20 for long-poll). Create DLQ `analyst-runs-dlq` (RedrivePolicy on main queue).

### Secrets & IAM

- [ ] T13 Create `deploy/aws/terraform/secrets.tf` — Secrets Manager entries:
       `analyst/anthropic_api_key` (placeholder), `analyst/neo4j_password` (placeholder),
       `analyst/mlflow_db_uri` (placeholder: postgresql://mlflow:<password>@<rds_endpoint>:5432/mlflow).
       (Values supplied out-of-band; Terraform stores only the secret names and metadata.)
- [ ] T14 Create `deploy/aws/terraform/iam.tf` — task execution role (allows
       secretsmanager:GetSecretValue, logs:*). Task roles: api (sqs:SendMessage on analyst-runs),
       worker (sqs:ReceiveMessage, sqs:DeleteMessage, sqs:ChangeMessageVisibility on analyst-runs,
       s3:* on mlflow bucket, read EFS). neo4j/mlflow roles read only from their mount points.

### Observability & opt-in GPU

- [ ] T15 Create `deploy/aws/terraform/observability.tf` — CloudWatch log groups
       `/ecs/analyst-api`, `/ecs/analyst-worker`, `/ecs/analyst-neo4j`, `/ecs/analyst-mlflow`,
       log retention 7 days. (Users can configure longer retention via env var.)
- [ ] T16 Create `deploy/aws/terraform/ollama-gpu.tf` — EC2 capacity provider (g5.xlarge, max weight
       1000), `ollama` ECS service (desired count = 0 by default, count = var.enable_ollama ? 1 : 0).
       Launch type mixed (Fargate + EC2). Auto-scaling group with min/max 0/2. When enabled, allows
       LLM_BACKEND=ollama without NAT egress.

### Outputs & final plumbing

- [ ] T17 Create `deploy/aws/terraform/outputs.tf` — output alb_dns_name, ecr_repo_uri, sqs_queue_url,
       efs_id, rds_endpoint, secrets_manager_arns (for documentation). Format for easy copy-paste into
       `.env`.
- [ ] T18 Test `terraform validate` (no syntax errors), `terraform plan` (green, idempotent).

**Exit (Track A):** `terraform plan` is clean and reports the creation of all resources; `terraform apply` succeeds (with placeholder secret values); all subnets, ECS cluster, ALB, EFS, RDS, SQS are healthy; `terraform output` returns the key values.

---

## Track B — ECR image push & API enqueue endpoints

### Image build & push

- [ ] T19 Add `make aws-ecr-push` target — builds the 0007 image (docker build using 0007 Dockerfile)
       and pushes to the ECR repository URL from Track A. Tag as `latest` and with git commit SHA.
       Confirm the image is pushed by running `aws ecr describe-images --repo-name analyst`.

### API enqueue endpoints

- [ ] T20 Create `api/runs.py` — POST /runs handler:
       - Input: `{handle: str, stages?: str = "all"}`.
       - Validate: handle is alphanumeric, stages is comma-list of ints 1–8.
       - Generate run_id = uuid.uuid4().hex[:12].
       - Write status marker to `{PROJECTS_DIR}/{handle}/runs/{run_id}.json`: `{run_id, status: "queued", created_at: ISO8601}`.
       - Send SQS message: `{run_id, handle, stages, enqueued_at: ISO8601}`.
       - Return 200: `{run_id, status: "queued", url: f"/runs/{run_id}"}`.
       - Error cases: invalid handle → 400, invalid stages → 400, SQS unreachable → 503.

- [ ] T21 Create GET /runs/{run_id} handler — read status marker from EFS; return `{run_id, status, ..., updated_at}`.
       If marker not found → 404. On error → 500.

- [ ] T22 Update `api/main.py` (FastAPI app) to include the /runs routes. Ensure the SQS client is created
       in `api/deps.py` and injected into the handlers. Set RUNS_QUEUE_URL from environment.

- [ ] T23 Update `docker/entrypoint.sh` to check if first arg is `api` or `worker` and branch accordingly.
       (Or confirm 0007's entrypoint already does this.)

- [ ] T24 Update `Makefile` — add `make aws-ecr-push` (builds + pushes image), update `make aws-run HANDLE=… STAGES=…`
       to invoke `aws ecs run-task` with the worker task definition.

**Exit (Track B):** ECR image is pushed and queryable; `POST /runs {"handle":"sample","stages":"1,2,3"}` returns
`{run_id, status:"queued"}` and a valid SQS message appears in the queue; `GET /runs/{id}` returns the status marker;
invalid inputs return 4xx; SQS down → 503.

---

## Track C — Worker task (SQS consumer loop)

### Worker implementation

- [ ] T25 Create `api/worker.py` — main entry point:
       - Initialize boto3 SQS client (from RUNS_QUEUE_URL).
       - Main loop: long-poll SQS (WaitTimeSeconds=20, MaxNumberOfMessages=1).
       - On message: extract run_id, handle, stages.
       - Update status marker to `{status: "running", started_at: ISO8601}`.
       - Call `profile_analyst.main(handle=handle, stages=stages)` (import from the CLI).
       - On success: update status marker to `{status: "succeeded", completed_at: ISO8601}`, delete message.
       - On exception: log error, update status to `{status: "failed", error: str(e), completed_at: ISO8601}`.
       - Handle SQS exceptions (ReceiveMessage errors) gracefully (log, continue loop).
       - Log all actions to stdout (captured by CloudWatch).

- [ ] T26 Handle poison messages (repeated failures) — track receive_count from message attributes.
       After N retries (default 3), do not delete the message (let visibility timeout expire → DLQ).
       Log a warning when a message is abandoned to DLQ.

- [ ] T27 Update `docker/entrypoint.sh` so that `entrypoint.sh worker` launches `python -m api.worker`.

### Integration with ECS RunTask

- [ ] T28 Verify the ECS task definition (Track A, T6) for the worker:
       - Image: ECR image URI.
       - Command: `["worker"]` (or entrypoint arg).
       - Environment: PROJECTS_DIR, RUNS_QUEUE_URL, ANTHROPIC_API_KEY (from secrets), LLM_BACKEND (anthropic, unless
         Ollama profile enabled), NEO4J_URI, etc.
       - Task role: can sqs:ReceiveMessage, sqs:DeleteMessage, read EFS, read secrets.
       - Log driver: CloudWatch.

### Makefile & CLI

- [ ] T29 Update `make aws-run HANDLE=sample STAGES=all` — runs `aws ecs run-task --cluster <cluster>
       --task-definition analyst-worker --launch-type FARGATE --network-configuration ...
       --overrides environment=[{name: HANDLE, value: sample}, {name: STAGES, value: all}]`.
       This is a one-shot invocation; the task runs to completion and exits.

**Exit (Track C):** `make aws-run HANDLE=sample STAGES=1,2,3` completes; `projects/sample/01-raw.json` through
`03-features.json` appear on EFS (schema-valid); status marker updates to `succeeded`; SQS message is deleted.
Running again for the same handle produces new artifacts (idempotent). Invalid handle → status `failed`, message
to DLQ.

---

## Track D — Integration & smoke tests

### Smoke tests

- [ ] T30 Create `tests/aws_smoke_test.py` (or shell script `deploy/aws/smoke_test.sh`) with 9 assertions:
       1. `terraform apply` succeeds; ALB target group has ≥1 healthy task.
       2. `curl https://<alb_dns>/healthz` → 200.
       3. `POST /runs {handle:sample}` → {run_id, status:queued}; message in SQS.
       4. After 1 min, `GET /runs/{id}` → status:succeeded; `projects/sample/01..08` on EFS, each schema-valid.
       5. `cypher-shell` confirms Neo4j has Creator/Signal/Score nodes.
       6. `POST /ask {question:...}` → grounded answer; mutation rejected.
       7. With Stage 8, `POST /rag` works.
       8. `docker history` has no secret values; `docker run` starts only after Secrets Manager resolves.
       9. Kill api task, restart; `projects/` and Neo4j graph persist.
       10. `make aws-run … erase --handle sample` → `projects/sample/` deleted.
       11. `make aws-run … invalid-handle` → status:failed, message to DLQ.

- [ ] T31 Update `Makefile` — add `make aws-smoke` target that runs the smoke test suite.

### Documentation & final validation

- [ ] T32 Update `deploy/aws/README.md` (create if missing) — runbook:
       - Prerequisites (AWS account, Terraform, Docker).
       - Bootstrap secrets in Secrets Manager (with example AWS CLI commands).
       - `terraform apply` full-stack provisioning.
       - `make aws-ecr-push` push image to ECR.
       - `make aws-run HANDLE=…` run a batch.
       - `make aws-smoke` run smoke tests.
       - Scaling & cost tuning (autoscaling, Fargate Spot, scale-to-zero in non-prod).
       - Debugging: CloudWatch log group locations, checking ALB health, inspecting EFS.
       - Cleanup: `terraform destroy` + empty S3 buckets.

- [ ] T33 Run `make validate` — confirm spec 0008 metadata.yml is valid, no schema errors.

- [ ] T34 Verify all code follows the repo's style (8-space indent, type hints, docstrings).
       Run `python -m pytest tests/` (existing tests still pass). Linter (if configured): `make lint`.

**Exit (Track D):** `make aws-smoke` passes all 11 assertions; all code is linted and type-checked;
`make validate` is green; the stack is end-to-end validated and documented.

---

## Final handoff

All four tracks completed: infrastructure live on AWS, API enqueue endpoints functional, worker task
consuming and running the pipeline, smoke tests passing. No push to remote; branch stays local for
user review. Ready for manual testing, cost analysis, and security review before merge.
