# ==============================================================================
# CargaExpress Infrastructure - RDS PostgreSQL Module Variables
# File: infrastructure/terraform/modules/rds/variables.tf
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

variable "database_name" {
  type        = string
  description = "Default operational database name (e.g. cargaexpress or opersolon)"
  default     = "cargaexpress"
}

variable "admin_username" {
  type        = string
  description = "Master administrative username for PostgreSQL"
  default     = "cargaexpress_admin"
}

variable "admin_password" {
  type        = string
  description = "Master administrative password (passed securely or generated)"
  sensitive   = true
}

variable "engine_version" {
  type        = string
  description = "PostgreSQL engine version"
  default     = "16.10"
}

variable "instance_class" {
  type        = string
  description = "RDS DB instance class"
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  type        = number
  description = "Initial allocated storage in GB (gp3)"
  default     = 20
}

variable "max_allocated_storage" {
  type        = number
  description = "Maximum storage limit for autoscaling in GB"
  default     = 100
}

variable "private_db_subnet_ids" {
  type        = list(string)
  description = "List of private database subnet IDs"
}

variable "rds_security_group_id" {
  type        = string
  description = "Security group ID allowing port 5432 ingress"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN for storage encryption"
}

variable "enable_multi_az" {
  type        = bool
  description = "Enable Multi-AZ deployment for high availability (default false for initial approved design)"
  default     = false
}

variable "backup_retention_period" {
  type        = number
  description = "Days of automated backup retention"
  default     = 1
}

variable "deletion_protection" {
  type        = bool
  description = "Protect database from accidental deletion"
  default     = true
}

variable "skip_final_snapshot" {
  type        = bool
  description = "Whether to skip final snapshot upon deletion (set true only for ephemeral dev environments)"
  default     = false
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
