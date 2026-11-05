# ==============================================================================
# CargaExpress Infrastructure - Staging AWS Provider Configuration
# File: infrastructure/terraform/environments/staging/providers.tf
# ==============================================================================

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Owner       = "CargaExpress-DevOps"
    }
  }
}
