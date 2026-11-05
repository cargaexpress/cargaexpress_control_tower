# ==============================================================================
# CargaExpress Infrastructure - Airflow & Batch Processing Module Variables
# File: infrastructure/terraform/modules/airflow/variables.tf
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

variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-east-2"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "ecs_cluster_id" {
  type        = string
  description = "ECS Cluster ID to host Airflow and Spark tasks"
}

variable "private_app_subnet_ids" {
  type        = list(string)
  description = "Private application subnet IDs"
}

variable "airflow_security_group_id" {
  type        = string
  description = "Security group ID for Airflow components"
}

variable "airflow_image" {
  type        = string
  description = "Docker image URI for Apache Airflow"
  default     = "apache/airflow:2.9.3"
}

variable "spark_image" {
  type        = string
  description = "Docker image URI for Spark ETL container"
}

variable "ecs_execution_role_arn" {
  type        = string
  description = "IAM Execution Role ARN"
}

variable "ecs_task_role_arn" {
  type        = string
  description = "IAM Task Role ARN"
}

variable "db_host" {
  type        = string
  description = "RDS PostgreSQL host address"
}

variable "db_port" {
  type        = number
  description = "RDS PostgreSQL port"
  default     = 5432
}

variable "db_user" {
  type        = string
  description = "Database username"
}

variable "db_password" {
  type        = string
  description = "Database password"
  sensitive   = true
}

variable "airflow_db_name" {
  type        = string
  description = "Airflow metadata database name in PostgreSQL"
  default     = "airflow"
}

variable "rabbitmq_url" {
  type        = string
  description = "RabbitMQ broker AMQP URL for Celery workers"
  sensitive   = true
}

variable "secretsmanager_airflow_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for Airflow Fernet key"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Key ARN for CloudWatch logs encryption"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "worker_desired_count" {
  type        = number
  description = "Desired number of Airflow Celery worker task replicas"
  default     = 1
}
