# ==============================================================================
# CargaExpress Infrastructure - Airflow & Batch Processing Module
# File: infrastructure/terraform/modules/airflow/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. CloudWatch Log Groups
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "webserver" {
  name              = "/ecs/${var.project_name}-${var.environment}-airflow-webserver"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "scheduler" {
  name              = "/ecs/${var.project_name}-${var.environment}-airflow-scheduler"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "celery_worker" {
  name              = "/ecs/${var.project_name}-${var.environment}-airflow-celery-worker"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "spark_etl" {
  name              = "/ecs/${var.project_name}-${var.environment}-spark-etl"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

# ------------------------------------------------------------------------------
# 2. Common Airflow Environment Configuration
# ------------------------------------------------------------------------------
locals {
  airflow_db_conn = "postgresql+psycopg2://${var.db_user}:${var.db_password}@${var.db_host}:${var.db_port}/${var.airflow_db_name}"

  common_airflow_env = [
    { name = "AIRFLOW__CORE__EXECUTOR", value = "CeleryExecutor" },
    { name = "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", value = local.airflow_db_conn },
    { name = "AIRFLOW__CELERY__RESULT_BACKEND", value = "db+${local.airflow_db_conn}" },
    { name = "AIRFLOW__CELERY__BROKER_URL", value = var.rabbitmq_url },
    { name = "AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION", value = "true" },
    { name = "AIRFLOW__CORE__LOAD_EXAMPLES", value = "false" },
    { name = "AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK", value = "true" },
    { name = "AIRFLOW__WEBSERVER__WORKERS", value = "2" }
  ]

  common_airflow_secrets = [
    { name = "AIRFLOW__CORE__FERNET_KEY", valueFrom = "${var.secretsmanager_airflow_secret_arn}:AIRFLOW__CORE__FERNET_KEY::" },
    { name = "AIRFLOW__WEBSERVER__SECRET_KEY", valueFrom = "${var.secretsmanager_airflow_secret_arn}:AIRFLOW__WEBSERVER__SECRET_KEY::" }
  ]
}

# ------------------------------------------------------------------------------
# 3. Airflow Webserver Task Definition & Service
# ------------------------------------------------------------------------------
resource "aws_ecs_task_definition" "webserver" {
  family                   = "${var.project_name}-${var.environment}-airflow-webserver"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" # 1 vCPU
  memory                   = "2048" # 2 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "airflow-webserver"
      image     = var.airflow_image
      essential = true
      command   = ["webserver"]
      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]
      environment = local.common_airflow_env
      secrets     = local.common_airflow_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.webserver.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "webserver"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "webserver" {
  name            = "${var.project_name}-${var.environment}-airflow-webserver-svc"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.webserver.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.airflow_security_group_id]
    assign_public_ip = false
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 4. Airflow Scheduler Task Definition & Service
# ------------------------------------------------------------------------------
resource "aws_ecs_task_definition" "scheduler" {
  family                   = "${var.project_name}-${var.environment}-airflow-scheduler"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" # 1 vCPU
  memory                   = "2048" # 2 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name        = "airflow-scheduler"
      image       = var.airflow_image
      essential   = true
      command     = ["scheduler"]
      environment = local.common_airflow_env
      secrets     = local.common_airflow_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.scheduler.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "scheduler"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "scheduler" {
  name            = "${var.project_name}-${var.environment}-airflow-scheduler-svc"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.scheduler.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.airflow_security_group_id]
    assign_public_ip = false
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 5. Airflow Celery Workers Task Definition & Service
# ------------------------------------------------------------------------------
resource "aws_ecs_task_definition" "celery_worker" {
  family                   = "${var.project_name}-${var.environment}-airflow-celery-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" # 1 vCPU
  memory                   = "2048" # 2 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name        = "celery-worker"
      image       = var.airflow_image
      essential   = true
      command     = ["celery", "worker"]
      environment = local.common_airflow_env
      secrets     = local.common_airflow_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.celery_worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "celery_worker" {
  name            = "${var.project_name}-${var.environment}-airflow-worker-svc"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.celery_worker.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.airflow_security_group_id]
    assign_public_ip = false
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 6. Spark ETL Jobs (4 vCPU Execution Configuration)
# ------------------------------------------------------------------------------
resource "aws_ecs_task_definition" "spark_etl" {
  family                   = "${var.project_name}-${var.environment}-spark-etl"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "4096"  # 4 vCPU execution configuration as specified in approved design
  memory                   = "16384" # 16 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "spark-etl-job"
      image     = var.spark_image
      essential = true
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.spark_etl.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "spark"
        }
      }
    }
  ])

  tags = merge(
    var.tags,
    {
      Role = "SparkBatchProcessing"
    }
  )
}
