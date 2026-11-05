# ==============================================================================
# CargaExpress Infrastructure - Bootstrap Outputs
# File: infrastructure/terraform/bootstrap/outputs.tf
# ==============================================================================

output "state_bucket_name" {
  value       = aws_s3_bucket.terraform_state.bucket
  description = "Name of the remote S3 state bucket to configure in backend.tf"
}

output "dynamodb_lock_table_name" {
  value       = aws_dynamodb_table.terraform_locks.name
  description = "Name of DynamoDB table for state locking"
}

output "backend_config_instructions" {
  value       = <<-EOT
    To configure your remote backend in staging and production:
    1. Update backend.tf with:
       bucket         = "${aws_s3_bucket.terraform_state.bucket}"
       region         = "${var.aws_region}"
       dynamodb_table = "${aws_dynamodb_table.terraform_locks.name}"
       encrypt        = true
       use_lockfile   = true
    2. Run: terraform init -migrate-state
  EOT
  description = "Instructions to migrate local state to S3 backend"
}
