# ==============================================================================
# CargaExpress Infrastructure - Security & IAM Module Outputs
# File: infrastructure/terraform/modules/security/outputs.tf
# ==============================================================================

output "kms_key_id" {
  value       = aws_kms_key.main.key_id
  description = "The ID of the KMS Customer Managed Key"
}

output "kms_key_arn" {
  value       = aws_kms_key.main.arn
  description = "The ARN of the KMS Customer Managed Key"
}

output "secretsmanager_db_secret_arn" {
  value       = aws_secretsmanager_secret.database.arn
  description = "The ARN of the Database credentials secret"
}

output "secretsmanager_rabbitmq_secret_arn" {
  value       = aws_secretsmanager_secret.rabbitmq.arn
  description = "The ARN of the RabbitMQ credentials secret"
}

output "secretsmanager_app_secrets_arn" {
  value       = aws_secretsmanager_secret.app_secrets.arn
  description = "The ARN of the Application/Carrier secrets"
}

output "secretsmanager_airflow_secret_arn" {
  value       = aws_secretsmanager_secret.airflow.arn
  description = "The ARN of the Airflow secrets"
}

output "ecs_execution_role_arn" {
  value       = aws_iam_role.ecs_execution_role.arn
  description = "The ARN of the ECS task execution role"
}

output "ecs_task_role_arn" {
  value       = aws_iam_role.ecs_task_role.arn
  description = "The ARN of the ECS task runtime role"
}
