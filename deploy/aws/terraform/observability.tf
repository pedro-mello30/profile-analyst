# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "ecs_api" {
  name              = "/ecs/${local.cluster_name}-api"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.cluster_name}-api-logs"
  }
}

resource "aws_cloudwatch_log_group" "ecs_neo4j" {
  name              = "/ecs/${local.cluster_name}-neo4j"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.cluster_name}-neo4j-logs"
  }
}

resource "aws_cloudwatch_log_group" "ecs_mlflow" {
  name              = "/ecs/${local.cluster_name}-mlflow"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.cluster_name}-mlflow-logs"
  }
}

resource "aws_cloudwatch_log_group" "ecs_worker" {
  name              = "/ecs/${local.cluster_name}-worker"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${local.cluster_name}-worker-logs"
  }
}
