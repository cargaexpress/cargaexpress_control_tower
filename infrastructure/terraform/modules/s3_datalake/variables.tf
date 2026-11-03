# ==============================================================================
# CargaExpress Infrastructure - S3 Data Lake Module Variables
# File: infrastructure/terraform/modules/s3_datalake/variables.tf
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

variable "aws_account_id" {
  type        = string
  description = "AWS Account ID for globally unique bucket naming"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN for S3 server-side encryption"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
