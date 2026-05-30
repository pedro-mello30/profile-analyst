.PHONY: validate test run install lint up down pull-models app api-logs

# ── Validation ──────────────────────────────────────────────────────────────
validate:
	@echo "==> Validating schemas and metadata..."
	python3 tools/validate.py
	@echo "==> OK"

# ── Tests ────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=pipeline --cov=adapters --cov-report=term-missing

# ── Run ──────────────────────────────────────────────────────────────────────
# Usage: make run HANDLE=<instagram_handle> [STAGE=all]
run:
	python3 profile_analyst.py --handle $(HANDLE) --stage $(or $(STAGE),all)

# ── Load (Stage 7: Neo4j graph persistence) ───────────────────────────────────
# Usage: make load HANDLE=<instagram_handle>
load:
	python3 profile_analyst.py --handle $(HANDLE) --stage 7

# ── GDS (Stage 9: graph data-science algorithms, spec 0004) ──────────────────
# Usage: make gds HANDLE=<instagram_handle>
gds:
	python3 profile_analyst.py gds --handle $(HANDLE)

# ── Ask (NL→Cypher graph query, spec 0003) ────────────────────────────────────
# Usage: make ask HANDLE=<instagram_handle> Q="<natural-language question>"
ask:
ifeq ($(strip $(HANDLE))$(strip $(Q)),)
	@echo "Usage: make ask HANDLE=<handle> Q=\"<question>\""
else ifeq ($(strip $(HANDLE)),)
	@echo "Usage: make ask HANDLE=<handle> Q=\"<question>\"  (HANDLE missing)"
else ifeq ($(strip $(Q)),)
	@echo "Usage: make ask HANDLE=<handle> Q=\"<question>\"  (Q missing)"
else
	python3 profile_analyst.py --handle $(HANDLE) --ask "$(Q)"
endif

# ── Embed (Stage 8: embedding backfill, spec 0005) ───────────────────────────
# Usage: make embed HANDLE=<instagram_handle>
embed:
ifeq ($(strip $(HANDLE)),)
	@echo "Usage: make embed HANDLE=<handle>"
else
	python3 profile_analyst.py --handle $(HANDLE) --stage 8
endif

# ── RAG (Hybrid RAG query, spec 0005) ────────────────────────────────────────
# Usage: make rag HANDLE=<instagram_handle> Q="<natural-language question>"
rag:
ifeq ($(strip $(Q)),)
	@echo "Usage: make rag HANDLE=<handle> Q=\"<question>\""
else
	python3 profile_analyst.py $(if $(strip $(HANDLE)),--handle $(HANDLE),) --rag "$(Q)"
endif

# Usage: make rag-rerank HANDLE=<instagram_handle> Q="<natural-language question>"
rag-rerank:
ifeq ($(strip $(Q)),)
	@echo "Usage: make rag-rerank HANDLE=<handle> Q=\"<question>\""
else
	python3 profile_analyst.py $(if $(strip $(HANDLE)),--handle $(HANDLE),) --rag "$(Q)" --rerank
endif

# ── Eval (RAG quality evaluation harness, spec 0006) ─────────────────────────
eval:
	OBSERVABILITY_ENABLED=true python3 -m observability.evaluation

# ── Install ──────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	ruff check . --fix

# ── Docker Compose (spec 0007) ────────────────────────────────────────────────
up:
	docker compose up -d

down:
	docker compose down

# Pull Ollama models into the volume via the ollama-pull init service.
pull-models:
	docker compose run --rm ollama-pull

# Run a one-shot pipeline command inside the app container.
# Usage: make app ARGS="--handle sample --stage all"
app:
	docker compose run --rm app-cli $(ARGS)

# Tail the API service logs.
api-logs:
	docker compose logs -f app-api

# ── AWS Fargate Deployment (spec 0008) ──────────────────────────────────────
# Build and push the app image to ECR.
# Requires: AWS_REGION, AWS credentials configured, ECR repository created.
# Usage: make aws-ecr-push ECR_REPO=<ecr-repo-uri>
aws-ecr-push:
ifeq ($(strip $(ECR_REPO)),)
	@echo "Usage: make aws-ecr-push ECR_REPO=<ecr-repo-uri> [TAG=<tag>]"
else
	@echo "==> Building image for ECR..."
	docker build -t analyst:latest -f docker/Dockerfile .
	@echo "==> Tagging image..."
	docker tag analyst:latest $(ECR_REPO):latest
	docker tag analyst:latest $(ECR_REPO):$(or $(TAG),$(shell git rev-parse --short HEAD)))
	@echo "==> Logging in to ECR..."
	aws ecr get-login-password --region $$(aws configure get region) | docker login --username AWS --password-stdin $(shell echo $(ECR_REPO) | cut -d'/' -f1)
	@echo "==> Pushing image..."
	docker push $(ECR_REPO):latest
	docker push $(ECR_REPO):$(or $(TAG),$(shell git rev-parse --short HEAD))
	@echo "==> Done. Image pushed to $(ECR_REPO)"
endif

# Start a one-shot worker task on AWS Fargate to process a batch run.
# Requires: AWS credentials, ECS cluster name, task definition, VPC/subnet config.
# Usage: make aws-run HANDLE=<handle> [STAGES=<stages>] [CLUSTER=<cluster>] [SUBNETS=<subnet-list>] [SECURITY_GROUPS=<sg-list>]
#
# Example: make aws-run HANDLE=sample STAGES=1,2,3 CLUSTER=analyst-dev SUBNETS=subnet-123,subnet-456 SECURITY_GROUPS=sg-123
aws-run:
ifeq ($(strip $(HANDLE)),)
	@echo "Usage: make aws-run HANDLE=<handle> [STAGES=<stages>] [CLUSTER=<cluster>] [SUBNETS=subnet-list] [SECURITY_GROUPS=sg-list]"
	@echo ""
	@echo "Example: make aws-run HANDLE=sample STAGES=1,2,3 CLUSTER=analyst-dev SUBNETS=subnet-123,subnet-456 SECURITY_GROUPS=sg-123"
else
	@echo "==> Starting worker task on ECS for handle=$(HANDLE), stages=$(or $(STAGES),all)..."
	aws ecs run-task \
		--cluster $(or $(CLUSTER),analyst-dev) \
		--task-definition analyst-worker \
		--launch-type FARGATE \
		--network-configuration "awsvpcConfiguration={subnets=[$(or $(SUBNETS),subnet-123)],securityGroups=[$(or $(SECURITY_GROUPS),sg-123)],assignPublicIp=DISABLED}" \
		--overrides "containerOverrides=[{name=analyst,environment=[{name=HANDLE,value=$(HANDLE)},{name=STAGES,value=$(or $(STAGES),all)}]}]" \
		--region $$(aws configure get region)
	@echo ""
	@echo "Task started. Monitor progress with: make aws-logs HANDLE=$(HANDLE)"
endif

# Tail CloudWatch logs for a worker task.
# Usage: make aws-logs HANDLE=<handle>
aws-logs:
ifeq ($(strip $(HANDLE)),)
	@echo "Usage: make aws-logs HANDLE=<handle>"
else
	aws logs tail /ecs/analyst-worker --follow --since 5m --region $$(aws configure get region)
endif

# Run smoke tests against a deployed Fargate instance.
# Usage: make aws-smoke ALB_DNS=<alb-dns-name> [HANDLE=<handle>]
aws-smoke:
ifeq ($(strip $(ALB_DNS)),)
	@echo "Usage: make aws-smoke ALB_DNS=<alb-dns-name> [HANDLE=<handle>]"
	@echo ""
	@echo "Example: make aws-smoke ALB_DNS=analyst-dev-123456789.us-east-1.elb.amazonaws.com"
else
	@echo "==> Running smoke tests against $(ALB_DNS)..."
	bash deploy/aws/smoke_test.sh $(ALB_DNS) $(or $(HANDLE),sample)
endif
