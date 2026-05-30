# Ollama ECS Service — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy Ollama as a Fargate service in the `analyst-dev` ECS cluster so that `/ask` (NL→Cypher) and `/rag` (hybrid RAG with embeddings) work end-to-end.

**Architecture:** `ollama/ollama:latest` runs as a single Fargate task, registered via Cloud Map as `ollama.analyst.local:11434`. Models persist on a dedicated EFS filesystem so model downloads only happen on first boot. API and Worker task definitions gain `OLLAMA_HOST` + model-selector env vars so they can reach the service.

**Tech Stack:** Terraform (AWS provider ~5.0), Fargate, EFS, Cloud Map, `ollama/ollama:latest` Docker image. Models used in dev: `nomic-embed-text` (~274 MB) for embeddings, `qwen2.5-coder:7b` (~4.7 GB) for NL→Cypher.

**Constraint — model sizes:** The spec defaults (`qwen2.5-coder:32b`, `qwen2.5:14b`) need 20+ GB RAM, which is expensive and slow on CPU. This plan uses `qwen2.5-coder:7b` for dev; override via the new `ollama_cypher_model` variable for staging/prod.

---

## Pre-flight

**Before starting, confirm the Terraform backend:**  
`override.tf` uses a local backend (`terraform.tfstate`). All `terraform` commands must be run from  
`deploy/aws/terraform/`. The state file is at `deploy/aws/terraform/terraform.tfstate`.

```bash
cd deploy/aws/terraform
terraform state list | grep ollama   # should return nothing (Ollama not deployed yet)
```

---

### Task 1: Add Ollama sizing variables

**Files:**
- Modify: `deploy/aws/terraform/variables.tf`

**Step 1: Add variables at the end of the Compute block (after `mlflow_memory` variable, before the Storage block)**

Find the line `# Storage` in `variables.tf` (currently line ~105) and insert before it:

```hcl
variable "desired_ollama_count" {
  description = "Desired number of Ollama task replicas (typically 1 for dev)"
  type        = number
  default     = 1
}

variable "ollama_cpu" {
  description = "Ollama task CPU units (4096 = 4 vCPU — needed for on-CPU inference)"
  type        = number
  default     = 4096
}

variable "ollama_memory" {
  description = "Ollama task memory in MB (16384 = 16 GB — needed for 7B model on CPU)"
  type        = number
  default     = 16384
}

variable "ollama_cypher_model" {
  description = "Ollama model for NL→Cypher (spec default: qwen2.5-coder:32b; use 7b for dev)"
  type        = string
  default     = "qwen2.5-coder:7b"
}

variable "ollama_embed_model" {
  description = "Ollama model for embeddings (spec default: nomic-embed-text)"
  type        = string
  default     = "nomic-embed-text"
}

variable "ollama_keep_alive" {
  description = "How long Ollama holds model warm between requests"
  type        = string
  default     = "10m"
}
```

**Step 2: Validate syntax**

```bash
cd deploy/aws/terraform && terraform validate
```

Expected: `Success! The configuration is valid.`

**Step 3: Commit**

```bash
git add deploy/aws/terraform/variables.tf
git commit -m "infra: add Ollama sizing variables (cpu/mem/model defaults)"
```

---

### Task 2: Add Ollama EFS filesystem

**Files:**
- Modify: `deploy/aws/terraform/storage.tf`

**Step 1: Append to `storage.tf` after the Neo4j EFS resources**

Add after the last `aws_efs_access_point` block (after line 96):

```hcl
# EFS Filesystem for Ollama model storage
resource "aws_efs_file_system" "ollama" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  tags = {
    Name = "${local.cluster_name}-ollama-efs"
  }
}

resource "aws_efs_mount_target" "ollama" {
  count           = var.availability_zones
  file_system_id  = aws_efs_file_system.ollama.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.ecs_tasks.id]
}

resource "aws_efs_access_point" "ollama_models" {
  file_system_id = aws_efs_file_system.ollama.id
  root_directory {
    path = "/models"
    creation_info {
      owner_gid   = 0
      owner_uid   = 0
      permissions = "0755"
    }
  }
  posix_user {
    gid = 0
    uid = 0
  }

  tags = {
    Name = "${local.cluster_name}-ollama-models-ap"
  }
}
```

**Step 2: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 3: Commit**

```bash
git add deploy/aws/terraform/storage.tf
git commit -m "infra: add EFS filesystem for Ollama model persistence"
```

---

### Task 3: Add CloudWatch log group

**Files:**
- Modify: `deploy/aws/terraform/observability.tf`

**Step 1: Append to `observability.tf`**

```hcl
resource "aws_cloudwatch_log_group" "ecs_ollama" {
  name              = "/ecs/${local.cluster_name}-ollama"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.cluster_name}-ollama-logs"
  }
}
```

**Step 2: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 3: Commit**

```bash
git add deploy/aws/terraform/observability.tf
git commit -m "infra: add CloudWatch log group for Ollama service"
```

---

### Task 4: Add Ollama IAM task role

**Files:**
- Modify: `deploy/aws/terraform/iam.tf`

**Step 1: Append to `iam.tf`** (after the MLflow role, before the GPU EC2 role block)

Find `# GPU EC2 IAM role` comment (around line 225) and insert before it:

```hcl
# Ollama Task Role (no extra AWS permissions needed — only logs via execution role)
resource "aws_iam_role" "ecs_task_role_ollama" {
  name = "${local.cluster_name}-ecs-task-role-ollama"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
      }
    ]
  })

  tags = {
    Name = "${local.cluster_name}-ecs-task-role-ollama"
  }
}
```

**Step 2: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 3: Commit**

```bash
git add deploy/aws/terraform/iam.tf
git commit -m "infra: add IAM task role for Ollama ECS service"
```

---

### Task 5: Add Ollama ECS task definition

**Files:**
- Modify: `deploy/aws/terraform/ecs.tf`

**Step 1: Append the task definition after the Worker task definition (after line 494, before the GPU AMI data source)**

The startup command pulls required models on first boot. Because models are stored on EFS (`/root/.ollama`), subsequent boots skip the download (Ollama checks if the model blob is already present).

```hcl
# ECS Task Definition for Ollama
resource "aws_ecs_task_definition" "ollama" {
  family                   = "${local.cluster_name}-ollama"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ollama_cpu
  memory                   = var.ollama_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role_ollama.arn

  container_definitions = jsonencode([
    {
      name      = "ollama"
      image     = "ollama/ollama:latest"
      cpu       = var.ollama_cpu
      memory    = var.ollama_memory
      essential = true

      portMappings = [
        {
          containerPort = 11434
          hostPort      = 11434
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "OLLAMA_MODELS"
          value = "/root/.ollama/models"
        },
        {
          name  = "OLLAMA_KEEP_ALIVE"
          value = var.ollama_keep_alive
        }
      ]

      # Starts daemon, waits until ready, pulls required models, then keeps running.
      # Ollama's pull is idempotent — skips if model blob already on EFS.
      command = [
        "/bin/sh", "-c",
        join(" && ", [
          "ollama serve &",
          "until curl -sf http://localhost:11434/api/version >/dev/null 2>&1; do sleep 2; done",
          "ollama pull ${var.ollama_embed_model}",
          "ollama pull ${var.ollama_cypher_model}",
          "wait"
        ])
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_ollama.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      mountPoints = [
        {
          sourceVolume  = "ollama_models"
          containerPath = "/root/.ollama"
          readOnly      = false
        }
      ]
    }
  ])

  volume {
    name = "ollama_models"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.ollama.id
      root_directory     = "/"
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.ollama_models.id
      }
    }
  }

  tags = {
    Name = "${local.cluster_name}-ollama"
  }
}
```

**Step 2: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 3: Commit**

```bash
git add deploy/aws/terraform/ecs.tf
git commit -m "infra: add Ollama ECS task definition with model pull on startup"
```

---

### Task 6: Update API and Worker task definitions to point at Ollama

**Files:**
- Modify: `deploy/aws/terraform/ecs.tf`

The API task definition currently has `LLM_BACKEND=anthropic` and no `OLLAMA_HOST`. The Worker has the same gap. Both need to know where Ollama lives and which models to use.

**Step 1: In the API task definition's `environment` array** (inside `aws_ecs_task_definition.api`, around line 118), add these entries:

```hcl
        {
          name  = "OLLAMA_HOST"
          value = "http://ollama.analyst.local:11434"
        },
        {
          name  = "OLLAMA_CYPHER_MODEL"
          value = var.ollama_cypher_model
        },
        {
          name  = "OLLAMA_EMBED_MODEL"
          value = var.ollama_embed_model
        },
        {
          name  = "OLLAMA_KEEP_ALIVE"
          value = var.ollama_keep_alive
        },
        {
          name  = "ASK_FALLBACK"
          value = "true"
        },
```

**Step 2: Do the same for the Worker task definition** (inside `aws_ecs_task_definition.worker`, around line 404) — add the same 5 entries to its `environment` array.

**Step 3: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 4: Commit**

```bash
git add deploy/aws/terraform/ecs.tf
git commit -m "infra: wire OLLAMA_HOST + model env vars into API and Worker task defs"
```

---

### Task 7: Add Ollama ECS service

**Files:**
- Modify: `deploy/aws/terraform/services.tf`

The Cloud Map entry `aws_service_discovery_service.ollama` already exists in `alb.tf` — it was pre-declared but never wired to a service. This task adds the actual ECS service.

**Step 1: Append to `services.tf`**

```hcl
# ECS Service for Ollama
resource "aws_ecs_service" "ollama" {
  name            = "${local.cluster_name}-ollama"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ollama.arn
  desired_count   = var.desired_ollama_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.ollama.arn
  }

  depends_on = [
    aws_iam_role_policy.ecs_task_execution_secrets,
    aws_efs_mount_target.ollama
  ]

  tags = {
    Name = "${local.cluster_name}-ollama"
  }
}
```

**Step 2: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 3: Commit**

```bash
git add deploy/aws/terraform/services.tf
git commit -m "infra: add Ollama ECS service with Cloud Map registration"
```

---

### Task 8: Add outputs

**Files:**
- Modify: `deploy/aws/terraform/outputs.tf`

**Step 1: Append to `outputs.tf`**

```hcl
output "ollama_task_definition_arn" {
  description = "Ollama task definition ARN"
  value       = aws_ecs_task_definition.ollama.arn
}

output "efs_ollama_id" {
  description = "ID of the EFS filesystem for Ollama model storage"
  value       = aws_efs_file_system.ollama.id
}
```

**Step 2: Validate**

```bash
cd deploy/aws/terraform && terraform validate
```

**Step 3: Commit**

```bash
git add deploy/aws/terraform/outputs.tf
git commit -m "infra: add Ollama outputs (task def ARN, EFS ID)"
```

---

### Task 9: Plan and apply

**Step 1: Preview the plan**

```bash
cd deploy/aws/terraform && terraform plan -out=tfplan-ollama
```

Expected new resources (approximately 7):
- `aws_efs_file_system.ollama`
- `aws_efs_mount_target.ollama[0]`, `[1]`
- `aws_efs_access_point.ollama_models`
- `aws_cloudwatch_log_group.ecs_ollama`
- `aws_iam_role.ecs_task_role_ollama`
- `aws_ecs_task_definition.ollama`
- `aws_ecs_service.ollama`

Plus 2 task definition updates (new revisions, no replacement):
- `aws_ecs_task_definition.api`
- `aws_ecs_task_definition.worker`

**Step 2: Apply**

```bash
terraform apply tfplan-ollama
```

Expected: `Apply complete! Resources: ~9 added, 2 changed, 0 destroyed.`

**Step 3: Force-redeploy API service to pick up new task definition revision**

```bash
aws ecs update-service \
  --cluster analyst-dev \
  --service analyst-dev-api \
  --force-new-deployment \
  --query "service.status" --output text
```

---

### Task 10: Smoke test

Ollama's first boot pulls models (~5 GB total). Budget ~10 minutes for the initial pull. The ECS service will be `ACTIVATING` until the model pull completes and the container passes its first health check.

**Step 1: Wait for Ollama to pull models**

```bash
# Watch until the Ollama task is RUNNING
aws ecs list-tasks --cluster analyst-dev --service-name analyst-dev-ollama --query "taskArns" --output text

# Stream Ollama logs to see model pull progress
aws logs tail /ecs/analyst-dev-ollama --follow
```

Expected in logs:
```
pulling manifest
pulling <layer>... ████ 100%
verifying sha256 digest
writing manifest
success
```

**Step 2: Confirm Cloud Map resolves**

From any ECS task, `ollama.analyst.local` should resolve. Verify via the API's healthz:

```bash
ALB="http://analyst-dev-alb-1648670454.us-east-1.elb.amazonaws.com"
curl -s "$ALB/healthz" | python3 -m json.tool
```

Expected:
```json
{
  "detail": {
    "status": "ok",
    "neo4j": "ok",
    "ollama": "ok"
  }
}
```

**Step 3: Test `/ask`**

```bash
curl -s -X POST "$ALB/ask" \
  -H "Content-Type: application/json" \
  -d '{"handle": "testuser", "question": "How many profiles are in the graph?"}' \
  | python3 -m json.tool
```

Expected: a JSON response with `cypher`, `results` (empty list — graph is empty), and `explanation` fields.

**Step 4: Test `/rag`**

```bash
curl -s -X POST "$ALB/rag" \
  -H "Content-Type: application/json" \
  -d '{"handle": "testuser", "question": "fitness influencer brand deals"}' \
  | python3 -m json.tool
```

Expected: a JSON response (empty results are fine — graph is empty, RAG will return no candidates).

**Step 5: Check CloudWatch for errors**

```bash
aws logs tail /ecs/analyst-dev-api --since 5m --format short | grep -i "error\|exception\|500"
```

Expected: no output.

---

## Rollback

If the Ollama service fails to stabilize after 15 minutes:

```bash
# Scale Ollama down (stops billing, lets you debug)
aws ecs update-service --cluster analyst-dev --service analyst-dev-ollama --desired-count 0

# API continues to work — ASK_FALLBACK=true will route /ask through Anthropic Claude
# /rag will still fail (no embeddings fallback exists)
```

To fully remove: `terraform destroy -target=aws_ecs_service.ollama` then work backwards through tasks 8→1.

---

## Notes

- **Neo4j password drift**: The Neo4j container uses `NEO4J_AUTH=neo4j/changeme` hardcoded; the Secrets Manager value was manually corrected to `changeme`. Terraform still emits `PLACEHOLDER_NEO4J_PASSWORD` for the secret version. A future cleanup task should wire the secret into the Neo4j task definition and remove the hardcoded value from `NEO4J_AUTH`.
- **Model sizes**: `qwen2.5-coder:7b` uses ~4.7 GB of the 16 GB RAM allocation. First-boot pull time on Fargate (NAT → Internet): ~8–12 minutes depending on ECS NAT gateway egress bandwidth.
- **EFS cost**: Ollama EFS at `bursting` throughput is ~$0.30/GB/month. A 7B model takes ~5 GB → ~$1.50/month.
