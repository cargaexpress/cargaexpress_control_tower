# ==============================================================================
# CargaExpress Infrastructure - Networking Module Variables
# File: infrastructure/terraform/modules/networking/variables.tf
# ==============================================================================

variable "project_name" {
  type        = string
  description = "Name of the project used for naming and tagging resources"
  default     = "cargaexpress"
}

variable "environment" {
  type        = string
  description = "Deployment environment name (e.g., production, staging)"
}

variable "aws_region" {
  type        = string
  description = "AWS region for deployment"
  default     = "us-east-2"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC Classless Inter-Domain Routing (CIDR) block"
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "List of two Availability Zones in the chosen region"
  default     = ["us-east-2a", "us-east-2b"]
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for public subnets (ALB, NAT Gateway)"
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_app_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for private application subnets (ECS, RabbitMQ, Airflow, Spark)"
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "private_db_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for private database subnets (RDS PostgreSQL)"
  default     = ["10.0.20.0/24", "10.0.21.0/24"]
}

variable "tags" {
  type        = map(string)
  description = "Common tags applied to all networking resources"
  default     = {}
}
