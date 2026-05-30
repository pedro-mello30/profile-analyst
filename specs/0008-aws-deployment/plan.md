# Plan 0008 — AWS Deployment (ECS Fargate)

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
Lifts the 0007 Docker topology to AWS: replaces local services with managed equivalents (ECS Fargate, RDS, S3, Secrets Manager), adds async batch orchestration via SQS, and keeps the 0007 image unchanged.

## Architecture (reference)

```
                            AWS region (single), ≥2 AZs
┌───────────────────────────────────────────────────────────────────────────────────┐
│  Internet ─ HTTPS (ACM) ─ ALB ─┐                                                   │
│                                 │  public subnets                                    │
│                                 ▼                                                    │
│                         ┌──────────────┐   private subnets (NAT for Anthropic API)  │
│                         │ ecs: api     │   POST /runs ─┬─ SQS ─┐                    │
│                         │ (Fargate)    │                │       ▼                    │
│                         │ /ask /rag    │ ◀─ GET /runs─┘   ┌─────────────┐          │
│                         │ /healthz     │                  │ ecs: worker │          │
│                         │ /runs        │                  │ (Fargate)   │          │
│                         └──┬────┬──────┘                  │ CLI mode    │          │
│                            │    │                        └────┬────────┘          │
│                            ▼    │                             │                    │
│                        ┌────────┐                         ┌────▼──────────┐        │
│                        │ neo4j  │                         │ EFS           │        │
│                        │Fargate │─ EFS (data) ◀──────────│ projects/     │        │
│                        └────────┘                         │ neo4j_data    │        │
│                            │                              └─┬──┬──────────┘        │
│                            └──────────────────────┬────────┘  │                    │
│                                                   ▼           ▼                    │
│                                             ┌──────────┐  ┌──────────┐             │
│                                             │ mlflow   │  │ postgres │             │
│                                             │Fargate   │  │ RDS      │             │
│                                             └──┬───────┘  └──────────┘             │
│                                                │                                   │
│                                       ┌────────┴────────┐                         │
│                                       ▼                 ▼                         │
│                                    ┌────────┐      ┌─────────┐                   │
│                                    │ S3     │      │ Secrets │                   │
│                                    │ mlflow │      │ Manager │                   │
│                                    │ artifacts  (valueFrom)                      │
│                                    └────────┘      └─────────┘                   │
│                                                                                   │
│  opt-in: EC2 GPU capacity provider ─ ollama (when LLM_BACKEND=ollama)             │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Every service uses the same 0007 image (no changes to pipeline logic). Secrets are never baked in; they arrive via Secrets Manager at task start. Artifacts live on EFS (multi-AZ). All compliance invariants carry over: Art.17 erasure on EFS, ToS gates, Art.9/Art.22 lineage.

## Implementation tracks (dependency-ordered)

### Track A — AWS Infrastructure (Terraform IaC)

Write the full Terraform module in `deploy/aws/terraform/` that provisions the AWS topology:
VPC with ≥2 AZs, public/private subnets, NAT gateway, ALB with HTTPS listener, ECS cluster
(Fargate + optional EC2 GPU capacity provider), task definitions for api/neo4j/mlflow/worker,
EFS filesystem with access points, RDS PostgreSQL (multi-AZ), S3 bucket for MLflow artifacts,
SQS queue + DLQ, Secrets Manager entries, IAM roles (least-privilege), Cloud Map private DNS
namespace, CloudWatch log groups. All resources defined idempotently in Terraform; `terraform plan`
is clean on re-run. State stored in S3 with DynamoDB lock.

Reference architecture in spec.md §4.1–4.3. Outputs: ALB DNS name, ECR repository URL, SQS
queue URL, EFS ID, RDS endpoint, secrets ARNs. No hard-coded secret values baked in; all injected
at task start via the `secrets` block (spec.md §5, G5).

Key IaC files (all created in `deploy/aws/terraform/`):
- `main.tf` — Terraform provider, S3 backend, required variables
- `network.tf` — VPC, subnets, NAT, VPC endpoints (S3, Secrets Manager)
- `ecs.tf` — cluster, capacity providers (Fargate base, optional EC2 GPU)
- `services.tf` — task definitions (api, neo4j, mlflow, worker) + ECS services
- `alb.tf` — ALB, listener (ACM 443), target group (→ /healthz)
- `efs.tf` — EFS + access points (projects, neo4j_data, neo4j_logs)
- `rds.tf` — RDS PostgreSQL (multi-AZ, backup)
- `s3.tf` — MLflow artifact bucket + TF state bucket
- `sqs.tf` — queue + DLQ
- `secrets.tf` — Secrets Manager entries (values supplied out-of-band via AWS console / AWS CLI)
- `iam.tf` — task execution roles (read secrets) + task roles (api: sqs:SendMessage; worker: sqs:Receive/Delete)
- `observability.tf` — CloudWatch log groups, Container Insights
- `ollama-gpu.tf` — opt-in EC2 capacity provider + ollama service (default `count = 0`)
- `variables.tf`, `outputs.tf` — inputs + outputs (ALB DNS, ECR URL, etc.)

**Exit (Track A):** `terraform plan` is clean and idempotent; `terraform apply` provisions all resources
(VPC through SQS, Secrets Manager entries with placeholder values, IAM roles); all AZ subnets healthy;
ALB target group created (even with 0 running tasks); `terraform output` returns all required values
(ALB DNS, ECR repo, queue URL, EFS ID, RDS endpoint).

---

### Track B — ECR image push & API enqueue endpoints

Push the 0007 Docker image to ECR (no changes to the image itself — it's the same artifact from 0007,
with the same `api` and CLI entrypoints). Write the API enqueue endpoints in `api/runs.py`:

- `POST /runs {handle: str, stages?: str = "all"}` → validate handle, generate run_id (UUID), write a
  `queued` status marker to `projects/<handle>/runs/<run_id>.json`, send an SQS message
  `{run_id, handle, stages}`, return `{run_id, status: "queued"}` (200 OK).
- `GET /runs/{run_id}` → read the status marker from EFS, return `{run_id, status: "queued|running|succeeded|failed", ...}` (200 OK or 404 if not found).
- Wire these into `api/main.py` (FastAPI app). Ensure `api/deps.py` provides an SQS client (boto3).
- Validation: `handle` is alphanumeric, `stages` is a comma-list of stage numbers. Invalid requests → 400.
- Error handling: if SQS is unreachable, return 503; if run_id is not a valid UUID, return 400.

Update `Makefile`: `make aws-ecr-push` → build + push the 0007 image to the ECR repo URL from Track A outputs.

**Exit (Track B):** ECR image is pushed and tagged; `POST /runs` and `GET /runs/{id}` endpoints are callable;
`POST /runs {"handle": "sample"}` returns `{run_id, status: "queued"}`; a valid SQS message lands in the queue;
invalid requests return 4xx; requests when SQS is down return 503.

---

### Track C — Worker task (SQS consumer loop)

Write `api/worker.py` — the worker task entrypoint that runs when the ECS worker task is invoked:

- Long-poll SQS queue for messages (boto3, `wait_time_seconds=20`, `max_number_of_messages=1`).
- On each message: extract `run_id`, `handle`, `stages`; update status marker to `running`;
  call `profile_analyst.main(handle=handle, stages=stages)` (the same entry point the CLI uses);
  catch exceptions and set status to `failed` (with error summary);
  on success, set status to `succeeded`.
- Delete the message from SQS on completion (success or failure). On repeated failure (>N retries),
  the message lands in the DLQ and the loop continues.
- Log all actions to CloudWatch (task stdout/stderr auto-captured).

Wire `worker.py` into the 0007 `docker/entrypoint.sh` so `ECS RunTask` with command `worker` launches
the loop. (Alternatively, make `worker` the default ENTRYPOINT and `api` a CLI arg; check 0007 convention.)

Update `Makefile`: `make aws-run HANDLE=sample STAGES=all` → `aws ecs run-task --cluster <cluster> --task-definition analyst-worker --launch-type FARGATE --network-configuration subnet-ids=… --overrides environment=[{name: HANDLE, value: sample}, {name: STAGES, value: all}]`
(runs a one-shot worker task).

**Exit (Track C):** `ECS RunTask` for the worker task definition completes; `profile_analyst main()` runs;
artifacts land on EFS; status marker updates to `succeeded`; SQS message is deleted; a second invocation
for the same handle produces new artifacts (idempotent re-run). Poison message (invalid handle) is retried
N times, then moved to DLQ, without crashing the loop.

---

### Track D — Integration & smoke tests

Write smoke tests in `tests/aws_smoke_test.py` (or similar):

1. **Stack provisioning:** `terraform apply` creates all resources.
2. **ALB health:** `curl https://<alb_dns>/healthz` returns 200 (target group healthy).
3. **Async batch run:** `curl -X POST https://<alb_dns>/runs -H "Content-Type: application/json" -d '{"handle":"sample"}'`
   returns `{run_id, status:"queued"}`; after ~1 min, `GET /runs/{run_id}` returns `status: "succeeded"`;
   `projects/sample/` on EFS contains `01-raw.json` through `08-dossier.json`, each schema-valid.
4. **Neo4j populated:** a worker run produces Signal/Score nodes in the cloud neo4j (verify via
   `cypher-shell -u neo4j -p <pwd> -a neo4j.analyst.local "MATCH (c:Creator) RETURN count(c)"`).
5. **Ask/RAG via API:** `POST /ask {"question":"list undisclosed sponsored posts for sample"}` returns
   a grounded answer; an injected mutation question is rejected (0003 A1/A2 hold). With Stage 8,
   `POST /rag` works (0005 A8 holds).
6. **Secrets injection:** `docker history` on the ECR image shows no secret values; tasks start only after
   Secrets Manager resolves them.
7. **Durable state:** killing and restarting the api task leaves `projects/` and the Neo4j graph intact.
8. **Erasure:** `make aws-run … erase --handle sample` removes `projects/sample/` on EFS (Art.17 holds).
9. **Poison message safety:** `make aws-run HANDLE=invalid-handle` ends `failed` and the message lands in DLQ
   without crashing the worker loop.

Update `Makefile`: `make aws-smoke` → runs all nine checks and reports success/failure.

**Exit (Track D):** All nine smoke tests pass; `make validate` is green; commits land on the
`spec-0008-finalize` branch (not pushed); the deployment is end-to-end validated and ready for manual
testing / review.

---

## Risks

| Risk | Mitigation |
|---|---|
| Secrets Manager value injection fails at task start | Ensure task execution role has `secretsmanager:GetSecretValue` + IAM secret policy allows the role; test with dummy secret before full deploy |
| EFS performance under load | v1 uses single EFS; document read-heavy workloads; DynamoDB (OQ3) if metadata querying scales |
| RDS replica lag (multi-AZ standby) | MLflow metadata is non-critical; RPO/RTO acceptable; document failover steps |
| Ollama GPU profile not tested in CI | Documented as opt-in; smoke test skips it by default; GPU host prerequisites documented in README |
| Terraform state lock contention | S3 + DynamoDB lock; document state cleanup (Lock stuck → unlock manually via AWS console) |
| SQS poison messages fill the DLQ | Monitor DLQ depth; document manual DLQ drain; default N=3 retries before DLQ |

---

## Open Questions (from metadata.yml §9)

- **OQ1:** Terraform vs CDK vs CloudFormation/Copilot — default Terraform (chosen). Confirm before implementing.
- **OQ2:** Worker trigger — `ECS RunTask`-per-message (default) vs always-on service. Default chosen (scales to zero). Revisit if cold-start latency is an issue.
- **OQ3:** Run-status store — EFS JSON marker (default) vs DynamoDB. Default chosen; consider DynamoDB if status queries become a bottleneck.
- **OQ4:** MLflow UI exposure — keep private (default) vs authenticated ALB path. Default chosen for v1.
- **OQ5:** Autoscaling — fixed desired-count (default) vs target-tracking. Default chosen; document scaling policies for future work.
- **OQ6:** Neo4j on Fargate+EFS (chosen) vs managed Neo4j AuraDB. Confirm before locking in.
