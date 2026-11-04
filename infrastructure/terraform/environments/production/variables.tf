# ==============================================================================
# CargaExpress Infrastructure - Production Environment Variables
# File: infrastructure/terraform/environments/production/variables.tf
# ==============================================================================

variable "project_name" {
  type        = string
  description = "Project identifier"
  default     = "cargaexpress"
}

variable "environment" {
  type        = string
  description = "Target deployment environment"
  default     = "production"
}

variable "aws_region" {
  type        = string
  description = "Target AWS Region"
  default     = "us-east-2"
}

variable "aws_account_id" {
  type        = string
  description = "Target AWS Account ID"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block"
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "Two target availability zones in us-east-2"
  default     = ["us-east-2a", "us-east-2b"]
}

variable "db_instance_class" {
  type        = string
  description = "RDS instance class"
  default     = "db.t4g.medium"
}

variable "db_name" {
  type        = string
  description = "Default operational database name"
  default     = "cargaexpress"
}

variable "db_admin_username" {
  type        = string
  description = "PostgreSQL administrator username"
  default     = "cargaexpress_admin"
}

variable "db_admin_password" {
  type        = string
  description = "PostgreSQL administrator password"
  sensitive   = true
}

variable "rabbitmq_password" {
  type        = string
  description = "RabbitMQ broker password"
  sensitive   = true
}

variable "backend_image" {
  type        = string
  description = "Docker image URI for backend Receiver & Query APIs"
  default     = "cargaexpress-backend:latest"
}

variable "worker_image" {
  type        = string
  description = "Docker image URI for background worker"
  default     = "cargaexpress-worker:latest"
}

variable "spark_image" {
  type        = string
  description = "Docker image URI for Spark ETL 4 vCPU job"
  default     = "cargaexpress-spark:latest"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository owner/name for OIDC"
  default     = "cargaexpress/cargaexpress_control_tower"
}

variable "alert_email" {
  type        = string
  description = "Email address for DevOps alert notifications"
  default     = "devops@cargaexpress.local"
}
