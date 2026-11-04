# ==============================================================================
# CargaExpress Infrastructure - Athena & Glue Catalog Module Variables
# File: infrastructure/terraform/modules/athena/variables.tf
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

variable "datalake_bucket_name" {
  type        = string
  description = "Name of the S3 Data Lake bucket holding the Gold layer"
}

variable "athena_results_bucket_name" {
  type        = string
  description = "Name of the S3 bucket holding Athena query results"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Key ARN for query result encryption"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
