# ==============================================================================
# CargaExpress Infrastructure - Production Environment Orchestration
# File: infrastructure/terraform/environments/production/main.tf
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ------------------------------------------------------------------------------
# 1. Networking Module (VPC, Subnets, NAT Gateway, Security Groups)
# ------------------------------------------------------------------------------
module "networking" {
  source = "../../modules/networking"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  tags               = local.common_tags
}

# ------------------------------------------------------------------------------
# 2. Security & IAM Module (KMS CMK, Secrets Manager, ECS Roles)
# ------------------------------------------------------------------------------
module "security" {
  source = "../../modules/security"

  project_name           = var.project_name
  environment            = var.environment
  aws_region             = var.aws_region
  aws_account_id         = var.aws_account_id
  s3_datalake_bucket_arn = module.s3_datalake.datalake_bucket_arn
  tags                   = local.common_tags
}

# ------------------------------------------------------------------------------
# 3. S3 Data Lake Module (Landing, Bronze, Silver, Gold Layers)
# ------------------------------------------------------------------------------
module "s3_datalake" {
  source = "../../modules/s3_datalake"

  project_name   = var.project_name
  environment    = var.environment
  aws_account_id = var.aws_account_id
  kms_key_arn    = module.security.kms_key_arn
  tags           = local.common_tags
}

# ------------------------------------------------------------------------------
# 4. Amazon RDS PostgreSQL Module (Private Isolated DB Subnets)
# ------------------------------------------------------------------------------
module "rds" {
  source = "../../modules/rds"

  project_name          = var.project_name
  environment           = var.environment
  database_name         = var.db_name
  admin_username        = var.db_admin_username
  admin_password        = var.db_admin_password
  instance_class        = var.db_instance_class
  private_db_subnet_ids = module.networking.private_db_subnet_ids
  rds_security_group_id = module.networking.rds_security_group_id
  kms_key_arn           = module.security.kms_key_arn
  enable_multi_az       = false # Initial approved Single-AZ design
  tags                  = local.common_tags
}

# ------------------------------------------------------------------------------
# 5. RabbitMQ Broker EC2 Module (Private Application Subnet)
# ------------------------------------------------------------------------------
module "rabbitmq" {
  source = "../../modules/rabbitmq"

  project_name               = var.project_name
  environment                = var.environment
  private_app_subnet_id      = module.networking.private_app_subnet_ids[0]
  rabbitmq_security_group_id = module.networking.rabbitmq_security_group_id
  kms_key_arn                = module.security.kms_key_arn
  rabbitmq_password          = var.rabbitmq_password
  tags                       = local.common_tags
}

# ------------------------------------------------------------------------------
# 6. Real-Time Processing - ECS Fargate Module (Receiver, APIs, Worker, ALB)
# ------------------------------------------------------------------------------
module "ecs" {
  source = "../../modules/ecs"

  project_name                   = var.project_name
  environment                    = var.environment
  aws_region                     = var.aws_region
  vpc_id                         = module.networking.vpc_id
  public_subnet_ids              = module.networking.public_subnet_ids
  private_app_subnet_ids         = module.networking.private_app_subnet_ids
  alb_security_group_id          = module.networking.alb_security_group_id
  ecs_security_group_id          = module.networking.ecs_security_group_id
  backend_image                  = var.backend_image
  worker_image                   = var.worker_image
  ecs_execution_role_arn         = module.security.ecs_execution_role_arn
  ecs_task_role_arn              = module.security.ecs_task_role_arn
  db_host                        = module.rds.address
  db_port                        = module.rds.port
  db_name                        = module.rds.database_name
  db_user                        = module.rds.admin_username
  db_password                    = var.db_admin_password
  rabbitmq_url                   = module.rabbitmq.amqp_url
  secretsmanager_app_secrets_arn = module.security.secretsmanager_app_secrets_arn
  kms_key_arn                    = module.security.kms_key_arn
  tags                           = local.common_tags
}

# ------------------------------------------------------------------------------
# 7. Orchestration & Batch Processing - Airflow & Spark Module
# ------------------------------------------------------------------------------
module "airflow" {
  source = "../../modules/airflow"

  project_name                      = var.project_name
  environment                       = var.environment
  aws_region                        = var.aws_region
  vpc_id                            = module.networking.vpc_id
  ecs_cluster_id                    = module.ecs.cluster_id
  private_app_subnet_ids            = module.networking.private_app_subnet_ids
  airflow_security_group_id         = module.networking.airflow_security_group_id
  spark_image                       = var.spark_image
  ecs_execution_role_arn            = module.security.ecs_execution_role_arn
  ecs_task_role_arn                 = module.security.ecs_task_role_arn
  db_host                           = module.rds.address
  db_port                           = module.rds.port
  db_user                           = module.rds.admin_username
  db_password                       = var.db_admin_password
  airflow_db_name                   = "airflow"
  rabbitmq_url                      = module.rabbitmq.amqp_url
  secretsmanager_airflow_secret_arn = module.security.secretsmanager_airflow_secret_arn
  kms_key_arn                       = module.security.kms_key_arn
  tags                              = local.common_tags
}

# ------------------------------------------------------------------------------
# 8. Analytical Query Engine - Amazon Athena & Glue Data Catalog Module
# ------------------------------------------------------------------------------
module "athena" {
  source = "../../modules/athena"

  project_name               = var.project_name
  environment                = var.environment
  datalake_bucket_name       = module.s3_datalake.datalake_bucket_name
  athena_results_bucket_name = module.s3_datalake.athena_results_bucket_name
  kms_key_arn                = module.security.kms_key_arn
  tags                       = local.common_tags
}

# ------------------------------------------------------------------------------
# 9. Monitoring & Container Registry - ECR & CloudWatch Module
# ------------------------------------------------------------------------------
locals {
  # Strip arn:aws:elasticloadbalancing:...:loadbalancer/ prefix to obtain ARN suffix
  alb_arn_suffix = replace(module.ecs.alb_arn, "/^arn:aws:elasticloadbalancing:[^:]+:[0-9]+:loadbalancer\\//", "")
}

module "monitoring" {
  source = "../../modules/monitoring"

  project_name     = var.project_name
  environment      = var.environment
  alb_arn_suffix   = local.alb_arn_suffix
  ecs_cluster_name = module.ecs.cluster_name
  rds_instance_id  = "${var.project_name}-${var.environment}-postgres"
  alert_email      = var.alert_email
  tags             = local.common_tags
}

# ------------------------------------------------------------------------------
# 10. CI/CD & GitHub OIDC Federation Module
# ------------------------------------------------------------------------------
module "cicd" {
  source = "../../modules/cicd"

  project_name      = var.project_name
  environment       = var.environment
  github_repository = var.github_repository
  tags              = local.common_tags
}
