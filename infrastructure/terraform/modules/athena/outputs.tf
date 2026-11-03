# ==============================================================================
# CargaExpress Infrastructure - Athena Module Outputs
# File: infrastructure/terraform/modules/athena/outputs.tf
# ==============================================================================

output "glue_database_name" {
  value       = aws_glue_catalog_database.gold.name
  description = "The Glue Data Catalog database name for Gold analytical data"
}

output "athena_workgroup_name" {
  value       = aws_athena_workgroup.analytics.name
  description = "The Athena Workgroup name"
}
