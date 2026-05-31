terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "profile-analyst-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "profile-analyst-tfstate-lock"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "profile-analyst"
      Env       = var.environment
      ManagedBy = "Terraform"
      CreatedAt = timestamp()
    }
  }
}

# Locals
locals {
  app_name      = var.app_name
  environment   = var.environment
  region        = var.aws_region
  cluster_name  = "${local.app_name}-${local.environment}"
  container_name = local.app_name
}
