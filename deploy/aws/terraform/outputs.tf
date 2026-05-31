output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = aws_lb.main.dns_name
}

output "alb_arn" {
  description = "ARN of the ALB"
  value       = aws_lb.main.arn
}

output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.app.repository_url
}

output "sqs_queue_url" {
  description = "URL of the SQS runs queue"
  value       = aws_sqs_queue.runs.url
}

output "sqs_queue_arn" {
  description = "ARN of the SQS runs queue"
  value       = aws_sqs_queue.runs.arn
}

output "efs_projects_id" {
  description = "ID of the EFS filesystem for projects"
  value       = aws_efs_file_system.projects.id
}

output "efs_neo4j_id" {
  description = "ID of the EFS filesystem for Neo4j"
  value       = aws_efs_file_system.neo4j.id
}

output "rds_cluster_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.mlflow.address
}

output "rds_cluster_reader_endpoint" {
  description = "RDS instance endpoint (read)"
  value       = aws_db_instance.mlflow.address
}

output "s3_mlflow_bucket" {
  description = "S3 bucket for MLflow artifacts"
  value       = aws_s3_bucket.mlflow.id
}

output "cloudmap_namespace_id" {
  description = "Cloud Map namespace ID"
  value       = aws_service_discovery_private_dns_namespace.main.id
}

output "cloudmap_namespace_name" {
  description = "Cloud Map namespace name"
  value       = aws_service_discovery_private_dns_namespace.main.name
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "api_task_definition_arn" {
  description = "API task definition ARN"
  value       = aws_ecs_task_definition.api.arn
}

output "worker_task_definition_arn" {
  description = "Worker task definition ARN"
  value       = aws_ecs_task_definition.worker.arn
}

output "neo4j_task_definition_arn" {
  description = "Neo4j task definition ARN"
  value       = aws_ecs_task_definition.neo4j.arn
}

output "mlflow_task_definition_arn" {
  description = "MLflow task definition ARN"
  value       = aws_ecs_task_definition.mlflow.arn
}

output "secrets_anthropic_api_key_arn" {
  description = "ARN of the Anthropic API key secret"
  value       = aws_secretsmanager_secret.anthropic_api_key.arn
}

output "secrets_neo4j_password_arn" {
  description = "ARN of the Neo4j password secret"
  value       = aws_secretsmanager_secret.neo4j_password.arn
}

output "secrets_mlflow_db_uri_arn" {
  description = "ARN of the MLflow DB URI secret"
  value       = aws_secretsmanager_secret.mlflow_db_uri.arn
}

output "ollama_task_definition_arn" {
  description = "Ollama task definition ARN"
  value       = aws_ecs_task_definition.ollama.arn
}

output "efs_ollama_id" {
  description = "ID of the EFS filesystem for Ollama model storage"
  value       = aws_efs_file_system.ollama.id
}

# Frontend Dashboard (spec 0009)
output "cloudfront_domain" {
  description = "CloudFront distribution domain for the frontend dashboard"
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "frontend_bucket_name" {
  description = "S3 bucket name for frontend static assets"
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (used for cache invalidation on deploy)"
  value       = aws_cloudfront_distribution.frontend.id
}

output "frontend_token_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the frontend API token"
  value       = aws_secretsmanager_secret.frontend_api_token.arn
  sensitive   = true
}
