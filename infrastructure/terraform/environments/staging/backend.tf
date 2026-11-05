# ==============================================================================
# CargaExpress Infrastructure - Staging S3 Remote State Backend
# File: infrastructure/terraform/environments/staging/backend.tf
# ==============================================================================
# S3 remote state storage with native state locking and KMS encryption.
# State bucket and DynamoDB locks provisioned via infrastructure/terraform/bootstrap
# ==============================================================================

terraform {
  backend "s3" {
    bucket       = "cargaexpress-tfstate-us-east-2-326204936524"
    key          = "staging/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true # Native S3 locking supported in Terraform >= 1.10
  }
}
