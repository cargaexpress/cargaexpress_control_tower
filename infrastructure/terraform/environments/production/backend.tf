# ==============================================================================
# CargaExpress Infrastructure - Production S3 Remote State Backend
# File: infrastructure/terraform/environments/production/backend.tf
# ==============================================================================
# S3 remote state storage with DynamoDB concurrency locking and native state locks.
#
# PREREQUISITE:
# The state bucket and lock table must exist before enabling this block.
# Deploy them once via:
#   cd infrastructure/terraform/bootstrap
#   terraform init && terraform apply
#
# TO MIGRATE FROM LOCAL STATE TO S3 BACKEND:
#   1. Uncomment the backend block below.
#   2. Replace <AWS_ACCOUNT_ID> with your AWS Account ID.
#   3. Run: terraform init -migrate-state
# ==============================================================================

# terraform {
#   backend "s3" {
#     bucket         = "cargaexpress-tfstate-us-east-2-<AWS_ACCOUNT_ID>"
#     key            = "production/terraform.tfstate"
#     region         = "us-east-2"
#     encrypt        = true
#     use_lockfile   = true # Native S3 locking supported in Terraform >= 1.10
#     dynamodb_table = "cargaexpress-tfstate-locks"
#   }
# }
