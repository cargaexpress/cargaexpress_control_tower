# ==============================================================================
# CargaExpress Infrastructure - Production S3 Remote State Backend
# File: infrastructure/terraform/environments/production/backend.tf
# ==============================================================================

# Note: S3 bucket and DynamoDB table for state locking must be provisioned
# prior to enabling this backend block.
# Command to migrate local state: terraform init -migrate-state

terraform {
  # backend "s3" {
  #   bucket         = "cargaexpress-terraform-state-us-east-2"
  #   key            = "production/terraform.tfstate"
  #   region         = "us-east-2"
  #   dynamodb_table = "cargaexpress-terraform-locks"
  #   encrypt        = true
  # }
}
