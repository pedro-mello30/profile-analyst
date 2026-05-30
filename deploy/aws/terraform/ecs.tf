# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = local.cluster_name

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = {
    Name = local.cluster_name
  }
}

# ECS Cluster Capacity Providers
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = concat(
    ["FARGATE", "FARGATE_SPOT"],
    var.enable_ollama_gpu_profile ? ["ec2-gpu"] : []
  )

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# EC2 Capacity Provider for GPU (optional)
resource "aws_ecs_capacity_provider" "gpu" {
  count = var.enable_ollama_gpu_profile ? 1 : 0
  name  = "ec2-gpu"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.gpu[0].arn
    managed_scaling {
      maximum_scaling_step_size = 1000
      minimum_scaling_step_size = 1
      status                    = "ENABLED"
      target_capacity           = 100
    }
  }
}

# Launch Template for GPU EC2 instances
resource "aws_launch_template" "gpu" {
  count           = var.enable_ollama_gpu_profile ? 1 : 0
  name_prefix     = "${local.cluster_name}-gpu-"
  image_id        = data.aws_ami.ecs_gpu[0].id
  instance_type   = "g5.xlarge"
  vpc_security_group_ids = [aws_security_group.ecs_tasks.id]

  iam_instance_profile {
    name = aws_iam_instance_profile.ecs_gpu[0].name
  }

  user_data = base64encode("#!/bin/bash\necho ECS_CLUSTER=${aws_ecs_cluster.main.name} >> /etc/ecs/ecs.config")

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${local.cluster_name}-gpu"
    }
  }
}

# Auto Scaling Group for GPU instances
resource "aws_autoscaling_group" "gpu" {
  count               = var.enable_ollama_gpu_profile ? 1 : 0
  name                = "${local.cluster_name}-gpu-asg"
  vpc_zone_identifier = aws_subnet.private[*].id
  min_size            = 0
  max_size            = 2
  desired_capacity    = 0
  health_check_type   = "ELB"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.gpu[0].id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${local.cluster_name}-gpu"
    propagate_at_launch = true
  }
}

# ECS Task Definition for API
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.cluster_name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role_api.arn

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = "${aws_ecr_repository.app.repository_url}:latest"
      cpu       = var.api_cpu
      memory    = var.api_memory
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "LLM_BACKEND"
          value = "anthropic"
        },
        {
          name  = "ALLOW_NONCOMPLIANT"
          value = "false"
        },
        {
          name  = "API_PORT"
          value = "8000"
        },
        {
          name  = "NEO4J_URI"
          value = "bolt://neo4j.analyst.local:7687"
        },
        {
          name  = "NEO4J_USER"
          value = "neo4j"
        },
        {
          name  = "NEO4J_DATABASE"
          value = "neo4j"
        },
        {
          name  = "MLFLOW_TRACKING_URI"
          value = "http://mlflow.analyst.local:5000"
        },
        {
          name  = "MLFLOW_ARTIFACTS_DESTINATION"
          value = "s3://${aws_s3_bucket.mlflow.id}/"
        },
        {
          name  = "RUNS_QUEUE_URL"
          value = aws_sqs_queue.runs.url
        },
        {
          name  = "PROJECTS_DIR"
          value = "/app/projects"
        },
        {
          name  = "OBSERVABILITY_ENABLED"
          value = "true"
        }
      ]

      secrets = [
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = "${aws_secretsmanager_secret.anthropic_api_key.arn}"
        },
        {
          name      = "NEO4J_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.neo4j_password.arn}"
        }
      ]

      command = ["api"]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_api.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      mountPoints = [
        {
          sourceVolume  = "projects"
          containerPath = "/app/projects"
          readOnly      = false
        }
      ]
    }
  ])

  volume {
    name = "projects"
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.projects.id
      root_directory          = "/"
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.projects.id
      }
    }
  }

  tags = {
    Name = "${local.cluster_name}-api"
  }
}

# ECS Task Definition for Neo4j
resource "aws_ecs_task_definition" "neo4j" {
  family                   = "${local.cluster_name}-neo4j"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.neo4j_cpu
  memory                   = var.neo4j_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role_neo4j.arn

  container_definitions = jsonencode([
    {
      name      = "neo4j"
      image     = "neo4j:5.13-community"
      cpu       = var.neo4j_cpu
      memory    = var.neo4j_memory
      essential = true

      portMappings = [
        {
          containerPort = 7687
          hostPort      = 7687
          protocol      = "tcp"
        },
        {
          containerPort = 7474
          hostPort      = 7474
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "NEO4J_AUTH"
          value = "neo4j/changeme"  # Will be overridden by secrets
        },
        {
          name  = "NEO4J_server_memory_heap_initial__size"
          value = "${var.neo4j_memory / 2}m"
        },
        {
          name  = "NEO4J_server_memory_heap_max__size"
          value = "${var.neo4j_memory / 2}m"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_neo4j.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      mountPoints = [
        {
          sourceVolume  = "neo4j_data"
          containerPath = "/var/lib/neo4j/data"
          readOnly      = false
        },
        {
          sourceVolume  = "neo4j_logs"
          containerPath = "/var/log/neo4j"
          readOnly      = false
        }
      ]
    }
  ])

  volume {
    name = "neo4j_data"
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.neo4j.id
      root_directory          = "/"
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.neo4j_data.id
      }
    }
  }

  volume {
    name = "neo4j_logs"
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.neo4j.id
      root_directory          = "/"
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.neo4j_logs.id
      }
    }
  }

  tags = {
    Name = "${local.cluster_name}-neo4j"
  }
}

# ECS Task Definition for MLflow
resource "aws_ecs_task_definition" "mlflow" {
  family                   = "${local.cluster_name}-mlflow"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.mlflow_cpu
  memory                   = var.mlflow_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role_mlflow.arn

  container_definitions = jsonencode([
    {
      name      = "mlflow"
      image     = "ghcr.io/mlflow/mlflow:v2.12.1"
      cpu       = var.mlflow_cpu
      memory    = var.mlflow_memory
      essential = true

      portMappings = [
        {
          containerPort = 5000
          hostPort      = 5000
          protocol      = "tcp"
        }
      ]

      command = [
        "mlflow",
        "server",
        "--host=0.0.0.0",
        "--port=5000",
        "--backend-store-uri=$(MLFLOW_BACKEND_STORE_URI)",
        "--default-artifact-root=$(MLFLOW_ARTIFACTS_DESTINATION)"
      ]

      environment = [
        {
          name  = "MLFLOW_ARTIFACTS_DESTINATION"
          value = "s3://${aws_s3_bucket.mlflow.id}/"
        }
      ]

      secrets = [
        {
          name      = "MLFLOW_BACKEND_STORE_URI"
          valueFrom = "${aws_secretsmanager_secret.mlflow_db_uri.arn}"
        },
        {
          name      = "AWS_ACCESS_KEY_ID"
          valueFrom = "${aws_secretsmanager_secret.mlflow_db_uri.arn}"  # Placeholder; use separate secret in production
        },
        {
          name      = "AWS_SECRET_ACCESS_KEY"
          valueFrom = "${aws_secretsmanager_secret.mlflow_db_uri.arn}"  # Placeholder; use separate secret in production
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_mlflow.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = {
    Name = "${local.cluster_name}-mlflow"
  }
}

# ECS Task Definition for Worker (batch jobs)
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.cluster_name}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role_worker.arn

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = "${aws_ecr_repository.app.repository_url}:latest"
      cpu       = var.api_cpu
      memory    = var.api_memory
      essential = true

      environment = [
        {
          name  = "LLM_BACKEND"
          value = "anthropic"
        },
        {
          name  = "ALLOW_NONCOMPLIANT"
          value = "false"
        },
        {
          name  = "NEO4J_URI"
          value = "bolt://neo4j.analyst.local:7687"
        },
        {
          name  = "NEO4J_USER"
          value = "neo4j"
        },
        {
          name  = "NEO4J_DATABASE"
          value = "neo4j"
        },
        {
          name  = "MLFLOW_TRACKING_URI"
          value = "http://mlflow.analyst.local:5000"
        },
        {
          name  = "MLFLOW_ARTIFACTS_DESTINATION"
          value = "s3://${aws_s3_bucket.mlflow.id}/"
        },
        {
          name  = "RUNS_QUEUE_URL"
          value = aws_sqs_queue.runs.url
        },
        {
          name  = "PROJECTS_DIR"
          value = "/app/projects"
        },
        {
          name  = "OBSERVABILITY_ENABLED"
          value = "true"
        }
      ]

      secrets = [
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = "${aws_secretsmanager_secret.anthropic_api_key.arn}"
        },
        {
          name      = "NEO4J_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.neo4j_password.arn}"
        }
      ]

      command = ["worker"]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_worker.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      mountPoints = [
        {
          sourceVolume  = "projects"
          containerPath = "/app/projects"
          readOnly      = false
        }
      ]
    }
  ])

  volume {
    name = "projects"
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.projects.id
      root_directory          = "/"
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.projects.id
      }
    }
  }

  tags = {
    Name = "${local.cluster_name}-worker"
  }
}

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

      command = [
        "/bin/sh", "-c",
        "ollama serve & until curl -sf http://localhost:11434/api/version >/dev/null 2>&1; do sleep 2; done && ollama pull ${var.ollama_embed_model} && ollama pull ${var.ollama_cypher_model} && wait"
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

# AMI for GPU instances
data "aws_ami" "ecs_gpu" {
  count = var.enable_ollama_gpu_profile ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-ecs-gpu-hvm-*"]
  }
}
