# ==============================================================================
# CargaExpress Infrastructure - Security & IAM Module Variables
# File: infrastructure/terraform/modules/security/variables.tf
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

variable "aws_account_id" {
  type        = string
  description = "AWS Account ID for resource policies"
}

variable "s3_datalake_bucket_arn" {
  type        = string
  description = "ARN of the S3 Data Lake bucket for task role policies"
  default     = ""
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
