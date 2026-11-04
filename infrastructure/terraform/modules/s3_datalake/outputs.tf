# ==============================================================================
# CargaExpress Infrastructure - S3 Data Lake Module Outputs
# File: infrastructure/terraform/modules/s3_datalake/outputs.tf
# ==============================================================================

output "datalake_bucket_name" {
  value       = aws_s3_bucket.datalake.id
  description = "Name of the main S3 Data Lake bucket"
}

output "datalake_bucket_arn" {
  value       = aws_s3_bucket.datalake.arn
  description = "ARN of the main S3 Data Lake bucket"
}

output "athena_results_bucket_name" {
  value       = aws_s3_bucket.athena_results.id
  description = "Name of the S3 bucket storing Athena query results"
}

output "athena_results_bucket_arn" {
  value       = aws_s3_bucket.athena_results.arn
  description = "ARN of the S3 bucket storing Athena query results"
}
