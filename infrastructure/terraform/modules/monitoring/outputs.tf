# ==============================================================================
# CargaExpress Infrastructure - Monitoring & ECR Module Outputs
# File: infrastructure/terraform/modules/monitoring/outputs.tf
# ==============================================================================

output "ecr_repository_urls" {
  value = {
    for k, v in aws_ecr_repository.repos : k => v.repository_url
  }
  description = "Map of ECR repository names to their registry URLs"
}

output "alerts_sns_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "The ARN of the SNS topic for operational alarms"
}
