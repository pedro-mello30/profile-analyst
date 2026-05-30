variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Application name (used in resource naming)"
  type        = string
  default     = "analyst"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

# Network
variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Number of AZs to use (min 2)"
  type        = number
  default     = 2
  validation {
    condition     = var.availability_zones >= 2
    error_message = "Must use at least 2 availability zones."
  }
}

variable "private_subnet_count" {
  description = "Number of private subnets (per AZ)"
  type        = number
  default     = 1
}

# Compute
variable "desired_api_count" {
  description = "Desired number of API task replicas"
  type        = number
  default     = 2
  validation {
    condition     = var.desired_api_count >= 1
    error_message = "Must have at least 1 API replica."
  }
}

variable "api_cpu" {
  description = "API task CPU (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "API task memory in MB"
  type        = number
  default     = 2048
}

variable "desired_neo4j_count" {
  description = "Desired number of Neo4j task replicas (typically 1)"
  type        = number
  default     = 1
}

variable "neo4j_cpu" {
  description = "Neo4j task CPU"
  type        = number
  default     = 2048
}

variable "neo4j_memory" {
  description = "Neo4j task memory in MB"
  type        = number
  default     = 4096
}

variable "desired_mlflow_count" {
  description = "Desired number of MLflow task replicas (typically 1)"
  type        = number
  default     = 1
}

variable "mlflow_cpu" {
  description = "MLflow task CPU"
  type        = number
  default     = 512
}

variable "mlflow_memory" {
  description = "MLflow task memory in MB"
  type        = number
  default     = 1024
}

# Storage
variable "enable_ollama_gpu_profile" {
  description = "Enable EC2 GPU capacity provider for Ollama (requires NVIDIA setup on host)"
  type        = bool
  default     = false
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_instance_class" {
  description = "RDS instance class (e.g., db.t3.micro, db.t3.small)"
  type        = string
  default     = "db.t3.micro"
}

variable "rds_backup_retention_days" {
  description = "RDS backup retention days"
  type        = number
  default     = 7
  validation {
    condition     = var.rds_backup_retention_days >= 0 && var.rds_backup_retention_days <= 35
    error_message = "Backup retention must be between 0 and 35 days."
  }
}

# Secrets
variable "secrets_manager_entries" {
  description = "Map of secret names to placeholder descriptions (actual values supplied via AWS console / CLI)"
  type        = map(string)
  default = {
    "analyst/anthropic_api_key"    = "Anthropic API key for Stage 3"
    "analyst/neo4j_password"       = "Neo4j password"
    "analyst/mlflow_db_uri"        = "MLflow PostgreSQL connection string"
    "analyst/postgres_password"    = "PostgreSQL (RDS) password"
    "analyst/minio_root_user"      = "MinIO root user (for future use)"
    "analyst/minio_root_password"  = "MinIO root password (for future use)"
  }
}

# Logging
variable "log_retention_days" {
  description = "CloudWatch log retention in days (0 = never expire)"
  type        = number
  default     = 7
}

variable "enable_container_insights" {
  description = "Enable ECS Container Insights"
  type        = bool
  default     = true
}

# Tags
variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for HTTPS listener (user must create/supply)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Additional tags to apply to resources"
  type        = map(string)
  default     = {}
}
