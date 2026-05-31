# ECS Service for API
resource "aws_ecs_service" "api" {
  name            = "${local.cluster_name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_api_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = local.container_name
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.https,
    aws_iam_role_policy.ecs_task_execution_secrets
  ]

  tags = {
    Name = "${local.cluster_name}-api"
  }
}

# ECS Service for Neo4j
resource "aws_ecs_service" "neo4j" {
  name            = "${local.cluster_name}-neo4j"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.neo4j.arn
  desired_count   = var.desired_neo4j_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.neo4j.arn
  }

  depends_on = [
    aws_iam_role_policy.ecs_task_execution_secrets,
    aws_efs_mount_target.neo4j
  ]

  tags = {
    Name = "${local.cluster_name}-neo4j"
  }
}

# ECS Service for MLflow
resource "aws_ecs_service" "mlflow" {
  name            = "${local.cluster_name}-mlflow"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mlflow.arn
  desired_count   = var.desired_mlflow_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.mlflow.arn
  }

  depends_on = [
    aws_iam_role_policy.ecs_task_execution_secrets,
    aws_db_instance.mlflow
  ]

  tags = {
    Name = "${local.cluster_name}-mlflow"
  }
}

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

# ECS Service for Worker (SQS consumer — async batch pipeline runs)
resource "aws_ecs_service" "worker" {
  name            = "${local.cluster_name}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.desired_worker_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  # No load_balancer / service_registries: the worker only long-polls SQS, it serves no traffic.
  depends_on = [
    aws_iam_role_policy.ecs_task_execution_secrets
  ]

  tags = {
    Name = "${local.cluster_name}-worker"
  }
}
