# ==============================================================================
# CargaExpress Infrastructure - Staging Environment Module Orchestration
# File: infrastructure/terraform/environments/staging/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Networking Module (VPC, Subnets, NAT GW, S3 VPC Gateway Endpoint, SGs)
# ------------------------------------------------------------------------------
module "networking" {
  source = "../../modules/networking"

  project_name             = var.project_name
  environment              = var.environment
  aws_region               = var.aws_region
  vpc_cidr                 = var.vpc_cidr
  availability_zones       = var.availability_zones
  public_subnet_cidrs      = ["10.1.1.0/24", "10.1.2.0/24"]
  private_app_subnet_cidrs = ["10.1.10.0/24", "10.1.11.0/24"]
  private_db_subnet_cidrs  = ["10.1.20.0/24", "10.1.21.0/24"]
  tags                     = local.common_tags
}

# ------------------------------------------------------------------------------
# 2. Security & IAM Module (KMS CMK, Secrets Manager, ECS Task Roles)
# ------------------------------------------------------------------------------
module "security" {
  source = "../../modules/security"

  project_name           = var.project_name
  environment            = var.environment
  aws_region             = var.aws_region
  aws_account_id         = local.aws_account_id
  s3_datalake_bucket_arn = module.s3_datalake.datalake_bucket_arn
  tags                   = local.common_tags
}

# ------------------------------------------------------------------------------
# 3. S3 Data Lake Module (Landing, Bronze, Silver, Gold, Athena Results)
# ------------------------------------------------------------------------------
module "s3_datalake" {
  source = "../../modules/s3_datalake"

  project_name   = var.project_name
  environment    = var.environment
  aws_account_id = local.aws_account_id
  kms_key_arn    = module.security.kms_key_arn
  tags           = local.common_tags
}

# ------------------------------------------------------------------------------
# 4. Relational Database Module (RDS PostgreSQL 16 Single-AZ Graviton)
# ------------------------------------------------------------------------------
module "rds" {
  source = "../../modules/rds"

  project_name          = var.project_name
  environment           = var.environment
  database_name         = var.db_name
  admin_username        = var.db_admin_username
  admin_password        = local.db_admin_password
  instance_class        = var.db_instance_class
  private_db_subnet_ids = module.networking.private_db_subnet_ids
  rds_security_group_id = module.networking.rds_security_group_id
  kms_key_arn           = module.security.kms_key_arn
  enable_multi_az       = false
  deletion_protection   = false
  skip_final_snapshot   = true
  tags                  = local.common_tags
}

# ------------------------------------------------------------------------------
# 5. Message Broker Module (RabbitMQ on EC2)
# ------------------------------------------------------------------------------
module "rabbitmq" {
  source = "../../modules/rabbitmq"

  project_name               = var.project_name
  environment                = var.environment
  instance_type              = "t3.small"
  private_app_subnet_id      = module.networking.private_app_subnet_ids[0]
  rabbitmq_security_group_id = module.networking.rabbitmq_security_group_id
  kms_key_arn                = module.security.kms_key_arn
  rabbitmq_password          = local.rabbitmq_password
  tags                       = local.common_tags
}

# ------------------------------------------------------------------------------
# 6. Container Platform Module (ECS Fargate Services & ALB)
# ------------------------------------------------------------------------------
module "ecs" {
  source = "../../modules/ecs"

  project_name                       = var.project_name
  environment                        = var.environment
  aws_region                         = var.aws_region
  vpc_id                             = module.networking.vpc_id
  public_subnet_ids                  = module.networking.public_subnet_ids
  private_app_subnet_ids             = module.networking.private_app_subnet_ids
  alb_security_group_id              = module.networking.alb_security_group_id
  acm_certificate_arn                = var.acm_certificate_arn
  ecs_security_group_id              = module.networking.ecs_security_group_id
  backend_image                      = local.backend_image
  worker_image                       = local.worker_image
  backend_desired_count              = var.backend_desired_count
  worker_desired_count               = var.worker_desired_count
  ecs_execution_role_arn             = module.security.ecs_execution_role_arn
  ecs_task_role_arn                  = module.security.ecs_task_role_arn
  db_host                            = module.rds.address
  db_port                            = module.rds.port
  db_name                            = module.rds.database_name
  db_user                            = module.rds.admin_username
  db_password                        = local.db_admin_password
  rabbitmq_url                       = module.rabbitmq.amqp_url
  secretsmanager_app_secrets_arn     = module.security.secretsmanager_app_secrets_arn
  secretsmanager_db_secret_arn       = module.security.secretsmanager_db_secret_arn
  secretsmanager_rabbitmq_secret_arn = module.security.secretsmanager_rabbitmq_secret_arn
  kms_key_arn                        = module.security.kms_key_arn
  tags                               = local.common_tags
}

# ------------------------------------------------------------------------------
# 7. Orchestration Module (Airflow & Spark Batch on ECS Fargate)
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
  spark_image                       = local.spark_image
  worker_desired_count              = 1 # Cost optimization: 1 Celery worker in staging
  ecs_execution_role_arn            = module.security.ecs_execution_role_arn
  ecs_task_role_arn                 = module.security.ecs_task_role_arn
  db_host                           = module.rds.address
  db_port                           = module.rds.port
  db_user                           = module.rds.admin_username
  db_password                       = local.db_admin_password
  airflow_db_name                   = "airflow"
  rabbitmq_url                      = module.rabbitmq.amqp_url
  secretsmanager_airflow_secret_arn = module.security.secretsmanager_airflow_secret_arn
  kms_key_arn                       = module.security.kms_key_arn
  tags                              = local.common_tags
}

# ------------------------------------------------------------------------------
# 8. Serverless Analytics Module (Amazon Athena Workgroup & Glue Catalog)
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
# 9. Observability & Monitoring Module (CloudWatch Alarms, ECR, SNS, Budgets)
# ------------------------------------------------------------------------------
module "monitoring" {
  source = "../../modules/monitoring"

  project_name         = var.project_name
  environment          = var.environment
  alb_arn_suffix       = local.alb_arn_suffix
  ecs_cluster_name     = module.ecs.cluster_name
  rds_instance_id      = "${var.project_name}-${var.environment}-postgres"
  alert_email          = var.alert_email
  monthly_budget_limit = var.monthly_budget_limit
  tags                 = local.common_tags
}

# ------------------------------------------------------------------------------
# 10. CI/CD Module (ECR Integration & GitHub Actions OIDC)
# ------------------------------------------------------------------------------
module "cicd" {
  source = "../../modules/cicd"

  project_name      = var.project_name
  environment       = var.environment
  github_repository = var.github_repository
  tags              = local.common_tags
}
