# EFS Filesystem
resource "aws_efs_file_system" "projects" {
  encrypted           = true
  performance_mode    = "generalPurpose"
  throughput_mode     = "bursting"

  tags = {
    Name = "${local.cluster_name}-projects-efs"
  }
}

resource "aws_efs_file_system" "neo4j" {
  encrypted           = true
  performance_mode    = "generalPurpose"
  throughput_mode     = "bursting"

  tags = {
    Name = "${local.cluster_name}-neo4j-efs"
  }
}

# EFS Mount Targets — one per AZ (regional EFS supports mount targets in every AZ)
resource "aws_efs_mount_target" "projects" {
  count           = var.availability_zones
  file_system_id  = aws_efs_file_system.projects.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.ecs_tasks.id]
}

resource "aws_efs_mount_target" "neo4j" {
  count           = var.availability_zones
  file_system_id  = aws_efs_file_system.neo4j.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.ecs_tasks.id]
}

# EFS Access Points
resource "aws_efs_access_point" "projects" {
  file_system_id = aws_efs_file_system.projects.id
  root_directory {
    path = "/projects"
    creation_info {
      owner_gid   = 10001
      owner_uid   = 10001
      permissions = "0755"
    }
  }
  posix_user {
    gid = 10001
    uid = 10001
  }

  tags = {
    Name = "${local.cluster_name}-projects-ap"
  }
}

resource "aws_efs_access_point" "neo4j_data" {
  file_system_id = aws_efs_file_system.neo4j.id
  root_directory {
    path = "/data"
    creation_info {
      owner_gid   = 7474
      owner_uid   = 7474
      permissions = "0755"
    }
  }
  posix_user {
    gid = 7474
    uid = 7474
  }

  tags = {
    Name = "${local.cluster_name}-neo4j-data-ap"
  }
}

resource "aws_efs_access_point" "neo4j_logs" {
  file_system_id = aws_efs_file_system.neo4j.id
  root_directory {
    path = "/logs"
    creation_info {
      owner_gid   = 7474
      owner_uid   = 7474
      permissions = "0755"
    }
  }
  posix_user {
    gid = 7474
    uid = 7474
  }

  tags = {
    Name = "${local.cluster_name}-neo4j-logs-ap"
  }
}

# RDS PostgreSQL for MLflow
resource "aws_db_subnet_group" "mlflow" {
  name       = "${local.cluster_name}-mlflow-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.cluster_name}-mlflow-db-subnet-group"
  }
}

resource "aws_db_instance" "mlflow" {
  identifier              = "${local.cluster_name}-mlflow"
  engine                  = "postgres"
  engine_version          = "15"
  instance_class          = var.rds_instance_class
  allocated_storage       = var.rds_allocated_storage
  db_name                 = "mlflow"
  username                = "mlflow"
  password                = random_password.rds_password.result
  db_subnet_group_name    = aws_db_subnet_group.mlflow.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  skip_final_snapshot     = true
  backup_retention_period = var.rds_backup_retention_days
  storage_encrypted       = true
  publicly_accessible     = false
  auto_minor_version_upgrade = false

  tags = {
    Name = "${local.cluster_name}-mlflow-instance"
  }
}

# Temporary password (replace with Secrets Manager lookup in production)
resource "random_password" "rds_password" {
  length  = 16
  special = true
}

# S3 Bucket for MLflow Artifacts
resource "aws_s3_bucket" "mlflow" {
  bucket              = "${data.aws_caller_identity.current.account_id}-${local.cluster_name}-mlflow"
  force_destroy       = false

  tags = {
    Name = "${local.cluster_name}-mlflow"
  }
}

resource "aws_s3_bucket_versioning" "mlflow" {
  bucket = aws_s3_bucket.mlflow.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "mlflow" {
  bucket = aws_s3_bucket.mlflow.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "mlflow" {
  bucket = aws_s3_bucket.mlflow.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 Bucket for Terraform state
resource "aws_s3_bucket" "terraform_state" {
  bucket              = "${data.aws_caller_identity.current.account_id}-${local.cluster_name}-terraform-state"
  force_destroy       = false

  tags = {
    Name = "${local.cluster_name}-terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# DynamoDB table for Terraform state lock
resource "aws_dynamodb_table" "terraform_lock" {
  name           = "${local.cluster_name}-tfstate-lock"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name = "${local.cluster_name}-tfstate-lock"
  }
}

# Data source for AWS account ID
data "aws_caller_identity" "current" {}

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
