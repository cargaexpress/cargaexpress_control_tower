# ==============================================================================
# CargaExpress Infrastructure - Monitoring & ECR Module Variables
# File: infrastructure/terraform/modules/monitoring/variables.tf
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

variable "alb_arn_suffix" {
  type        = string
  description = "ARN suffix of the ALB for CloudWatch metric dimensions"
}

variable "ecs_cluster_name" {
  type        = string
  description = "ECS cluster name for CloudWatch metric dimensions"
}

variable "rds_instance_id" {
  type        = string
  description = "RDS instance identifier for CloudWatch metric dimensions"
}

variable "alert_email" {
  type        = string
  description = "Email address for CloudWatch alarm notifications"
  default     = "devops@cargaexpress.local"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
