# ==============================================================================
# CargaExpress Infrastructure - Staging S3 Remote State Backend
# File: infrastructure/terraform/environments/staging/backend.tf
# ==============================================================================

terraform {
  # backend "s3" {
  #   bucket         = "cargaexpress-terraform-state-us-east-2"
  #   key            = "staging/terraform.tfstate"
  #   region         = "us-east-2"
  #   dynamodb_table = "cargaexpress-terraform-locks"
  #   encrypt        = true
  # }
}
