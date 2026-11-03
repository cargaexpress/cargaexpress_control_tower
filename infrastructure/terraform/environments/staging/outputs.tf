# ==============================================================================
# CargaExpress Infrastructure - Staging Environment Outputs
# File: infrastructure/terraform/environments/staging/outputs.tf
# ==============================================================================

output "alb_dns_name" {
  value       = module.ecs.alb_dns_name
  description = "Public URL and entry point for Webhooks and Query APIs"
}

output "rds_endpoint" {
  value       = module.rds.endpoint
  description = "Connection endpoint for RDS PostgreSQL"
}

output "rabbitmq_private_ip" {
  value       = module.rabbitmq.private_ip
  description = "Internal IP address of RabbitMQ broker"
}

output "datalake_bucket_name" {
  value       = module.s3_datalake.datalake_bucket_name
  description = "Main S3 Data Lake bucket name"
}

output "athena_workgroup_name" {
  value       = module.athena.athena_workgroup_name
  description = "Athena workgroup for analytical and Power BI queries"
}

output "glue_database_name" {
  value       = module.athena.glue_database_name
  description = "AWS Glue Catalog database for the analytical Gold star schema"
}

output "ecr_repository_urls" {
  value       = module.monitoring.ecr_repository_urls
  description = "Map of ECR repository URLs for Docker image pushes"
}

output "github_actions_role_arn" {
  value       = module.cicd.github_actions_role_arn
  description = "IAM Role ARN to configure in GitHub Actions Secrets (AWS_ROLE_ARN)"
}
