# ==============================================================================
# CargaExpress Infrastructure - Bootstrap Variables
# File: infrastructure/terraform/bootstrap/variables.tf
# ==============================================================================

variable "aws_region" {
  type        = string
  description = "Target AWS Region"
  default     = "us-east-2"

  validation {
    condition     = var.aws_region == "us-east-2"
    error_message = "CargaExpress infrastructure is strictly restricted to us-east-2 (Ohio)."
  }
}

variable "aws_account_id" {
  type        = string
  description = "Target AWS Account ID (optional, auto-detected from caller identity)"
  default     = null
}
