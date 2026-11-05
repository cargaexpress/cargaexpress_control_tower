# ==============================================================================
# CargaExpress Infrastructure - CI/CD & GitHub OIDC Module Variables
# File: infrastructure/terraform/modules/cicd/variables.tf
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

variable "github_repository" {
  type        = string
  description = "GitHub repository formatted as 'owner/repo' (e.g. 'cargaexpress/cargaexpress_control_tower')"
  default     = "*/*"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "create_oidc_provider" {
  type        = bool
  description = "Whether to create the GitHub OIDC provider resource (default true for fresh accounts)"
  default     = true
}
