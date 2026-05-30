# ECR Repository
resource "aws_ecr_repository" "app" {
  name                 = local.cluster_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = local.cluster_name
  }
}

# ECS Task Execution Role (for pulling images, logging, secrets)
resource "aws_iam_role" "ecs_task_execution_role" {
  name               = "${local.cluster_name}-ecs-task-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${local.cluster_name}-ecs-task-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name   = "${local.cluster_name}-ecs-task-execution-secrets"
  role   = aws_iam_role.ecs_task_execution_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.anthropic_api_key.arn,
          aws_secretsmanager_secret.neo4j_password.arn,
          aws_secretsmanager_secret.mlflow_db_uri.arn
        ]
      }
    ]
  })
}

# API Task Role
resource "aws_iam_role" "ecs_task_role_api" {
  name               = "${local.cluster_name}-ecs-task-role-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${local.cluster_name}-ecs-task-role-api"
  }
}

resource "aws_iam_role_policy" "ecs_task_role_api_sqs" {
  name   = "${local.cluster_name}-ecs-task-role-api-sqs"
  role   = aws_iam_role.ecs_task_role_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.runs.arn
      }
    ]
  })
}

# Worker Task Role
resource "aws_iam_role" "ecs_task_role_worker" {
  name               = "${local.cluster_name}-ecs-task-role-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${local.cluster_name}-ecs-task-role-worker"
  }
}

resource "aws_iam_role_policy" "ecs_task_role_worker_sqs" {
  name   = "${local.cluster_name}-ecs-task-role-worker-sqs"
  role   = aws_iam_role.ecs_task_role_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.runs.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_role_worker_s3" {
  name   = "${local.cluster_name}-ecs-task-role-worker-s3"
  role   = aws_iam_role.ecs_task_role_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:*"
        ]
        Resource = [
          aws_s3_bucket.mlflow.arn,
          "${aws_s3_bucket.mlflow.arn}/*"
        ]
      }
    ]
  })
}

# Neo4j Task Role
resource "aws_iam_role" "ecs_task_role_neo4j" {
  name               = "${local.cluster_name}-ecs-task-role-neo4j"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${local.cluster_name}-ecs-task-role-neo4j"
  }
}

# MLflow Task Role
resource "aws_iam_role" "ecs_task_role_mlflow" {
  name               = "${local.cluster_name}-ecs-task-role-mlflow"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${local.cluster_name}-ecs-task-role-mlflow"
  }
}

resource "aws_iam_role_policy" "ecs_task_role_mlflow_s3" {
  name   = "${local.cluster_name}-ecs-task-role-mlflow-s3"
  role   = aws_iam_role.ecs_task_role_mlflow.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:*"
        ]
        Resource = [
          aws_s3_bucket.mlflow.arn,
          "${aws_s3_bucket.mlflow.arn}/*"
        ]
      }
    ]
  })
}

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

# GPU EC2 IAM role and instance profile
resource "aws_iam_role" "ecs_gpu" {
  count = var.enable_ollama_gpu_profile ? 1 : 0
  name  = "${local.cluster_name}-ecs-gpu-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_gpu_policy" {
  count      = var.enable_ollama_gpu_profile ? 1 : 0
  role       = aws_iam_role.ecs_gpu[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "ecs_gpu" {
  count = var.enable_ollama_gpu_profile ? 1 : 0
  name  = "${local.cluster_name}-ecs-gpu-profile"
  role  = aws_iam_role.ecs_gpu[0].name
}
