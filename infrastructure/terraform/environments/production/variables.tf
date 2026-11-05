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

  validation {
    condition     = var.environment == "production"
    error_message = "This environment module is designated strictly for production."
  }
}

variable "aws_region" {
  type        = string
  description = "Target AWS Region"
  default     = "us-east-2"

  validation {
    condition     = var.aws_region == "us-east-2"
    error_message = "CargaExpress infrastructure is strictly restricted to us-east-2 (Ohio)."
  }
}

variable "aws_account_id" {
  type        = string
  description = "Target AWS Account ID (optional; auto-detected from caller identity if omitted)"
  default     = null
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block"
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block (e.g. 10.0.0.0/16)."
  }
}

variable "availability_zones" {
  type        = list(string)
  description = "Two target availability zones in us-east-2"
  default     = ["us-east-2a", "us-east-2b"]

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "Exactly two availability zones are required for high availability."
  }
}

variable "db_instance_class" {
  type        = string
  description = "RDS instance class (production workload)"
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
  description = "PostgreSQL administrator password (loaded from TF_VAR_db_admin_password or auto-generated)"
  sensitive   = true
  default     = null
}

variable "rabbitmq_password" {
  type        = string
  description = "RabbitMQ broker password (loaded from TF_VAR_rabbitmq_password or auto-generated)"
  sensitive   = true
  default     = null
}

variable "backend_image" {
  type        = string
  description = "Docker image URI for backend Receiver & Query APIs (optional; auto-concatenated from account, region, project and env)"
  default     = null
}

variable "worker_image" {
  type        = string
  description = "Docker image URI for background worker (optional; auto-concatenated from account, region, project and env)"
  default     = null
}

variable "spark_image" {
  type        = string
  description = "Docker image URI for Spark ETL 4 vCPU job (optional; auto-concatenated from account, region, project and env)"
  default     = null
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

variable "backend_desired_count" {
  type        = number
  description = "Desired number of Receiver and API task replicas in production (Multi-AZ HA)"
  default     = 2
}

variable "worker_desired_count" {
  type        = number
  description = "Desired number of background worker task replicas in production (Multi-AZ HA)"
  default     = 2
}

variable "monthly_budget_limit" {
  type        = number
  description = "Approved monthly AWS budget in USD (null until approved by management)"
  default     = null
}

variable "acm_certificate_arn" {
  type        = string
  description = "ACM Certificate ARN for ALB HTTPS listener (optional; set when SSL certificate is available)"
  default     = null
}
