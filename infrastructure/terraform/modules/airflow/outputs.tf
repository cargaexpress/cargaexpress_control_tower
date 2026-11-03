# ==============================================================================
# CargaExpress Infrastructure - Airflow Module Outputs
# File: infrastructure/terraform/modules/airflow/outputs.tf
# ==============================================================================

output "webserver_service_name" {
  value       = aws_ecs_service.webserver.name
  description = "Airflow webserver ECS service name"
}

output "scheduler_service_name" {
  value       = aws_ecs_service.scheduler.name
  description = "Airflow scheduler ECS service name"
}

output "celery_worker_service_name" {
  value       = aws_ecs_service.celery_worker.name
  description = "Airflow Celery worker ECS service name"
}

output "spark_task_definition_arn" {
  value       = aws_ecs_task_definition.spark_etl.arn
  description = "ARN of the 4 vCPU Spark ETL task definition for Airflow ECS operator"
}
