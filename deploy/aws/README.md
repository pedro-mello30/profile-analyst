# AWS Fargate Deployment — Runbook

Deploy the profile-analyst pipeline on AWS ECS Fargate with always-on API service and async worker batch processing.

**Documentation:** See `specs/0008-aws-deployment/spec.md` for full architecture and compliance details.

## Prerequisites

- **AWS Account** with appropriate IAM permissions (EC2, ECS, RDS, S3, SQS, Secrets Manager, CloudWatch)
- **Terraform 1.5+** (`terraform --version`)
- **Docker** (`docker --version`)
- **AWS CLI 2.x** (`aws --version`) with credentials configured (`aws configure`)
- **Git** with SSH keys configured for GitHub (if using private ECR)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ AWS Account                                                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ VPC (10.0.0.0/16)                                           │  │
│  │                                                              │  │
│  │  ┌──────────────┐              ┌──────────────────────┐   │  │
│  │  │   Internet   │              │   ALB (443/80)       │   │  │
│  │  │   Gateway    │◄────────────►│   Health Check       │   │  │
│  │  └──────────────┘              └──────────────────────┘   │  │
│  │                                          │                 │  │
│  │  ┌──────────────────────────────────────┼──────────────┐  │  │
│  │  │ Private Subnets (2+ AZs)             │              │  │  │
│  │  │                                      ▼              │  │  │
│  │  │  ┌──────────┐      ┌────────┐   ┌────────┐        │  │  │
│  │  │  │   API    │      │ Worker │   │Neo4j   │        │  │  │
│  │  │  │ Service  │      │ Tasks  │   │ Node   │        │  │  │
│  │  │  │(Fargate) │      │(Fargate)   │        │        │  │  │
│  │  │  └──────────┘      └────────┘   └────────┘        │  │  │
│  │  │         │                │            │            │  │  │
│  │  │         └────────┬───────┴────────────┘            │  │  │
│  │  │                  ▼                                 │  │  │
│  │  │         ┌──────────────┐                          │  │  │
│  │  │         │     EFS      │                          │  │  │
│  │  │         │  (projects/) │                          │  │  │
│  │  │         └──────────────┘                          │  │  │
│  │  │                                                    │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │ Data Tier                                        │  │  │
│  │  │  • RDS Aurora PostgreSQL (MLflow metadata)       │  │  │
│  │  │  • S3 (MLflow artifacts)                         │  │  │
│  │  │  • SQS (batch queue) + DLQ                       │  │  │
│  │  │  • Secrets Manager (API keys, passwords)        │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│ CloudWatch Logs (/ecs/analyst-{api,worker,neo4j,mlflow})     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Step 1: Bootstrap Secrets

Create placeholder secret values in AWS Secrets Manager. These will be referenced by ECS task definitions.

```bash
# Set your API keys and passwords
export ANTHROPIC_API_KEY="sk-ant-..."
export NEO4J_PASSWORD="your-neo4j-password"
export POSTGRES_PASSWORD="your-postgres-password"

# Create secrets
aws secretsmanager create-secret \
  --name analyst/anthropic_api_key \
  --secret-string "$ANTHROPIC_API_KEY"

aws secretsmanager create-secret \
  --name analyst/neo4j_password \
  --secret-string "$NEO4J_PASSWORD"

aws secretsmanager create-secret \
  --name analyst/mlflow_db_uri \
  --secret-string "postgresql://mlflow:${POSTGRES_PASSWORD}@analyst.local:5432/mlflow"
```

## Step 2: Create ACM Certificate

The ALB requires an HTTPS certificate. Create or import one in AWS Certificate Manager.

```bash
# Option A: Request a new certificate for your domain
aws acm request-certificate \
  --domain-name example.com \
  --validation-method DNS

# Option B: Import an existing certificate
aws acm import-certificate \
  --certificate-body file://cert.pem \
  --certificate-chain file://chain.pem \
  --private-key file://key.pem
```

Copy the certificate ARN for use in Step 3.

## Step 3: Provision Infrastructure with Terraform

Initialize Terraform and review the plan:

```bash
cd deploy/aws/terraform

# Initialize (downloads provider plugins, configures backend)
terraform init

# Review the plan (no resources created yet)
terraform plan -out=tfplan

# Apply the plan (creates all AWS resources)
terraform apply tfplan

# Export outputs for later use
terraform output > ../outputs.txt
```

**Key resources created:**
- VPC (10.0.0.0/16) with 2+ AZs
- ECS cluster with Fargate capacity provider
- ALB with HTTPS listener (using your ACM certificate)
- RDS Aurora PostgreSQL instance
- EFS for shared /projects storage
- SQS queue + DLQ for batch jobs
- CloudWatch log groups for all services
- ECR repository for the application image

**Outputs to note:**
- `alb_dns_name` — DNS name of the load balancer
- `ecr_repo_uri` — ECR repository URI (for image push)
- `sqs_queue_url` — SQS queue URL (for job enqueueing)
- `efs_id` — EFS filesystem ID (for mounting)
- `rds_endpoint` — RDS database endpoint (for MLflow)

## Step 4: Build and Push Docker Image

Build the application image (from Spec 0007) and push to ECR:

```bash
# Build the image (Dockerfile in docker/Dockerfile)
make aws-ecr-push ECR_REPO=<ecr-repo-uri-from-step-3>

# Verify the image was pushed
aws ecr describe-images --repository-name analyst

# Note the image URI for manual task creation:
# <aws-account-id>.dkr.ecr.<region>.amazonaws.com/analyst:latest
```

## Step 5: Deploy Services

Once Terraform apply completes, the ECS services (api, neo4j, mlflow) are automatically created and started:

```bash
# Check service status
aws ecs describe-services \
  --cluster analyst-dev \
  --services analyst-api

# Tail API service logs
aws logs tail /ecs/analyst-api --follow

# Check ALB target health
aws elbv2 describe-target-health \
  --target-group-arn <target-group-arn>
```

## Step 6: Enqueue Your First Batch Job

Use the API or Makefile to enqueue a pipeline run:

```bash
# Option A: Use curl
curl -X POST https://<alb-dns>/runs \
  -H "Content-Type: application/json" \
  -d '{"handle": "sample", "stages": "1,2,3"}'

# Option B: Use Makefile (requires ECS permissions to launch tasks)
make aws-run HANDLE=sample STAGES=1,2,3 \
  CLUSTER=analyst-dev \
  SUBNETS=subnet-123,subnet-456 \
  SECURITY_GROUPS=sg-123

# Poll status
curl https://<alb-dns>/runs/<run-id>?handle=sample

# Tail worker logs
aws logs tail /ecs/analyst-worker --follow
```

## Step 7: Run Smoke Tests

Validate the full deployment with smoke tests:

```bash
# Run the smoke test suite
./deploy/aws/smoke_test.sh <alb-dns> sample

# Or use the Makefile target (requires AWS credentials)
make aws-smoke ALB_DNS=<alb-dns>
```

## Operational Runbook

### Monitor Logs

```bash
# Tail all ECS logs
aws logs tail /ecs/analyst-api --follow
aws logs tail /ecs/analyst-worker --follow
aws logs tail /ecs/analyst-neo4j --follow
aws logs tail /ecs/analyst-mlflow --follow
```

### Scale the API Service

```bash
# Increase desired count to 3
aws ecs update-service \
  --cluster analyst-dev \
  --service analyst-api \
  --desired-count 3

# Check task counts
aws ecs describe-services \
  --cluster analyst-dev \
  --services analyst-api
```

### Check SQS Queue Depth

```bash
# Monitor queue messages
aws sqs get-queue-attributes \
  --queue-url <sqs-queue-url> \
  --attribute-names All

# Check DLQ for failed messages
aws sqs get-queue-attributes \
  --queue-url <sqs-dlq-url> \
  --attribute-names All
```

### Update Task Environment Variables

Edit the task definition and update the service:

```bash
aws ecs register-task-definition \
  --family analyst-api \
  --container-definitions <json-with-updated-env>

aws ecs update-service \
  --cluster analyst-dev \
  --service analyst-api \
  --force-new-deployment
```

### Troubleshooting

**Service failing to start:**
- Check logs: `aws logs tail /ecs/analyst-api`
- Verify secrets exist: `aws secretsmanager list-secrets`
- Check IAM permissions: task execution role needs `secretsmanager:GetSecretValue`

**Pipeline not executing:**
- Verify SQS queue is receiving messages: `aws sqs receive-message --queue-url <url>`
- Check worker logs: `aws logs tail /ecs/analyst-worker --follow`
- Verify EFS is mounted: worker logs should show `/app/projects` directory operations

**Database connection errors:**
- Verify RDS is healthy: `aws rds describe-db-instances`
- Check security group rules: RDS should allow port 5432 from ECS task SG
- Verify MLflow DB URI in Secrets Manager

## Cost Optimization

1. **Use Fargate Spot** for non-critical workloads (up to 70% savings)
2. **Scale to zero** during non-business hours using scheduled tasks
3. **RDS Reserved Instances** for long-term commitments (up to 60% savings)
4. **S3 Lifecycle Policies** to transition old MLflow artifacts to Glacier
5. **EBS/EFS Autoscaling** to avoid over-provisioning storage

## Security Best Practices

1. **Secrets Manager** — never commit API keys or passwords
2. **VPC Endpoints** — for S3 and Secrets Manager (no NAT gateway egress)
3. **Security Groups** — follow least-privilege principle
4. **ALB → HTTPS only** — HTTP redirects to HTTPS
5. **CloudWatch Logs** — retention policy prevents unbounded growth
6. **ECR Image Scanning** — enable to detect vulnerabilities
7. **Network policies** — restrict ECS task egress to necessary services

## Cleanup

To destroy all resources and avoid ongoing charges:

```bash
cd deploy/aws/terraform
terraform destroy
```

This will delete all AWS resources except:
- Secrets Manager entries (must delete manually or in console)
- S3 buckets with versioning enabled (may need force delete if not empty)
- CloudWatch log groups (may need manual cleanup)

---

**See Also:**
- Spec 0008: `specs/0008-aws-deployment/spec.md`
- Terraform Plan: `specs/0008-aws-deployment/plan.md`
- Docker Spec: `specs/0007-docker-deployment/spec.md`
