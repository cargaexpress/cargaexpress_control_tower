# ==============================================================================
# CargaExpress Infrastructure - Production Local Values & Dynamic Resolutions
# File: infrastructure/terraform/environments/production/locals.tf
# ==============================================================================

# Dynamic Caller Identity & Random Password Fallbacks
data "aws_caller_identity" "current" {}

resource "random_password" "db_password" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "random_password" "rabbitmq_password" {
  length  = 24
  special = false
}

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    Owner       = "CargaExpress-DevOps"
  }

  # 1. Dynamic AWS Account ID Resolution
  aws_account_id = var.aws_account_id != null && var.aws_account_id != "" ? var.aws_account_id : data.aws_caller_identity.current.account_id

  # 2. Dynamic Passwords Resolution (TF_VAR_* or securely generated)
  db_admin_password = var.db_admin_password != null && var.db_admin_password != "" ? var.db_admin_password : random_password.db_password.result
  rabbitmq_password = var.rabbitmq_password != null && var.rabbitmq_password != "" ? var.rabbitmq_password : random_password.rabbitmq_password.result

  # 3. Dynamic ECR Image URI Concatenation
  backend_image = var.backend_image != null && var.backend_image != "" ? var.backend_image : "${local.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project_name}-backend:${var.environment}"
  worker_image  = var.worker_image != null && var.worker_image != "" ? var.worker_image : "${local.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project_name}-worker:${var.environment}"
  spark_image   = var.spark_image != null && var.spark_image != "" ? var.spark_image : "${local.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project_name}-spark:${var.environment}"

  # 4. ALB ARN suffix for CloudWatch metrics
  alb_arn_suffix = replace(module.ecs.alb_arn, "/^arn:aws:elasticloadbalancing:[^:]+:[0-9]+:loadbalancer\\//", "")
}
