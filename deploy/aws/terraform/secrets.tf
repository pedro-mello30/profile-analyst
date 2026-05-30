# Secrets Manager secrets
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "analyst/anthropic_api_key"
  description             = "Anthropic API key for Stage 3"
  recovery_window_in_days = 7

  tags = {
    Name = "${local.cluster_name}-anthropic-key"
  }
}

resource "aws_secretsmanager_secret" "neo4j_password" {
  name                    = "analyst/neo4j_password"
  description             = "Neo4j database password"
  recovery_window_in_days = 7

  tags = {
    Name = "${local.cluster_name}-neo4j-password"
  }
}

resource "aws_secretsmanager_secret" "mlflow_db_uri" {
  name                    = "analyst/mlflow_db_uri"
  description             = "MLflow PostgreSQL connection string"
  recovery_window_in_days = 7

  tags = {
    Name = "${local.cluster_name}-mlflow-db-uri"
  }
}

# Placeholder secret values (user should update via AWS console or aws secretsmanager put-secret-value)
resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = "PLACEHOLDER_ANTHROPIC_API_KEY"  # User must update
}

resource "aws_secretsmanager_secret_version" "neo4j_password" {
  secret_id     = aws_secretsmanager_secret.neo4j_password.id
  secret_string = "PLACEHOLDER_NEO4J_PASSWORD"  # User must update
}

resource "aws_secretsmanager_secret_version" "mlflow_db_uri" {
  secret_id     = aws_secretsmanager_secret.mlflow_db_uri.id
  secret_string = "postgresql://mlflow:PLACEHOLDER_PASSWORD@${aws_rds_cluster.mlflow.endpoint}:5432/mlflow"  # User must update
}
