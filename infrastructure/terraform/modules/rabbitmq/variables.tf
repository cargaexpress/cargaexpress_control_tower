# ==============================================================================
# CargaExpress Infrastructure - RabbitMQ EC2 Module Variables
# File: infrastructure/terraform/modules/rabbitmq/variables.tf
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

variable "instance_type" {
  type        = string
  description = "EC2 instance type for RabbitMQ"
  default     = "t3.medium"
}

variable "private_app_subnet_id" {
  type        = string
  description = "Private application subnet ID to launch the EC2 instance in"
}

variable "rabbitmq_security_group_id" {
  type        = string
  description = "Security group ID for RabbitMQ broker"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN for EBS encryption"
}

variable "volume_size" {
  type        = number
  description = "Size of EBS root volume in GB"
  default     = 30
}

variable "rabbitmq_username" {
  type        = string
  description = "Default administrative username for RabbitMQ"
  default     = "cargaexpress"
}

variable "rabbitmq_password" {
  type        = string
  description = "Administrative password for RabbitMQ"
  sensitive   = true
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
