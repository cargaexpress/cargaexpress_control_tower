# ==============================================================================
# CargaExpress Infrastructure - CI/CD & GitHub OIDC Module Outputs
# File: infrastructure/terraform/modules/cicd/outputs.tf
# ==============================================================================

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "The IAM Role ARN to configure in GitHub Actions (AWS_ROLE_ARN secret)"
}
