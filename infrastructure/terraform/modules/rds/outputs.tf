# ==============================================================================
# CargaExpress Infrastructure - RDS PostgreSQL Module Outputs
# File: infrastructure/terraform/modules/rds/outputs.tf
# ==============================================================================

output "endpoint" {
  value       = aws_db_instance.main.endpoint
  description = "The connection endpoint for the RDS PostgreSQL database"
}

output "address" {
  value       = aws_db_instance.main.address
  description = "The DNS hostname of the RDS PostgreSQL instance"
}

output "port" {
  value       = aws_db_instance.main.port
  description = "The database port"
}

output "database_name" {
  value       = aws_db_instance.main.db_name
  description = "The name of the default operational database"
}

output "admin_username" {
  value       = aws_db_instance.main.username
  description = "Master username for the database"
}

output "resource_id" {
  value       = aws_db_instance.main.resource_id
  description = "RDS Resource ID"
}

output "arn" {
  value       = aws_db_instance.main.arn
  description = "The ARN of the RDS instance"
}
