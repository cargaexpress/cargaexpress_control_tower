# ==============================================================================
# CargaExpress Infrastructure - ECS Fargate Module Variables
# File: infrastructure/terraform/modules/ecs/variables.tf
# ==============================================================================

variable "project_name" {
  type        = string
  description = "Project name"
  default     = "cargaexpress"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-east-2"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnet IDs for the ALB"
}

variable "private_app_subnet_ids" {
  type        = list(string)
  description = "Private application subnet IDs for Fargate tasks"
}

variable "alb_security_group_id" {
  type        = string
  description = "Security group ID for the ALB"
}

variable "ecs_security_group_id" {
  type        = string
  description = "Security group ID for ECS Fargate services"
}

variable "backend_image" {
  type        = string
  description = "Docker image URI for the backend service (Receiver and API)"
}

variable "worker_image" {
  type        = string
  description = "Docker image URI for the worker service"
}

variable "ecs_execution_role_arn" {
  type        = string
  description = "IAM Execution Role ARN for ECS agent"
}

variable "ecs_task_role_arn" {
  type        = string
  description = "IAM Task Role ARN for runtime permissions"
}

variable "db_host" {
  type        = string
  description = "RDS PostgreSQL host address"
}

variable "db_port" {
  type        = number
  description = "RDS PostgreSQL port"
  default     = 5432
}

variable "db_name" {
  type        = string
  description = "Database name"
  default     = "cargaexpress"
}

variable "db_user" {
  type        = string
  description = "Database master username"
}

variable "db_password" {
  type        = string
  description = "Database master password"
  sensitive   = true
}

variable "rabbitmq_url" {
  type        = string
  description = "RabbitMQ AMQP URL"
  sensitive   = true
}

variable "secretsmanager_app_secrets_arn" {
  type        = string
  description = "Secrets Manager ARN for application secrets"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Key ARN for CloudWatch logs encryption"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
