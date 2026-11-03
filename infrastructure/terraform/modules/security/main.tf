# ==============================================================================
# CargaExpress Infrastructure - Security & IAM Module
# File: infrastructure/terraform/modules/security/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. AWS KMS Customer Managed Key (CMK)
# ------------------------------------------------------------------------------
resource "aws_kms_key" "main" {
  description             = "KMS CMK for ${var.project_name}-${var.environment} encryption at rest"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootPermissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Principal = {
          Service = "logs.${var.aws_region}.amazonaws.com"
        }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*"
        ]
        Resource = "*"
      }
    ]
  })

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-kms-key"
    }
  )
}

resource "aws_kms_alias" "main" {
  name          = "alias/${var.project_name}-${var.environment}"
  target_key_id = aws_kms_key.main.key_id
}

# ------------------------------------------------------------------------------
# 2. AWS Secrets Manager Secrets
# ------------------------------------------------------------------------------

# Database Master Credentials
resource "aws_secretsmanager_secret" "database" {
  name                    = "${var.project_name}/${var.environment}/database"
  description             = "PostgreSQL RDS connection details and credentials"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    username = "cargaexpress_admin"
    password = "CHANGE_ME_IN_PRODUCTION_VIA_SECRETS_MANAGER"
    engine   = "postgres"
    port     = 5432
    database = "cargaexpress"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# RabbitMQ Broker Credentials
resource "aws_secretsmanager_secret" "rabbitmq" {
  name                    = "${var.project_name}/${var.environment}/rabbitmq"
  description             = "RabbitMQ AMQP connection details and credentials"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "rabbitmq" {
  secret_id = aws_secretsmanager_secret.rabbitmq.id
  secret_string = jsonencode({
    username = "cargaexpress"
    password = "CHANGE_ME_IN_PRODUCTION_VIA_SECRETS_MANAGER"
    port     = 5672
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Application & Carrier Secrets
resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "${var.project_name}/${var.environment}/app_secrets"
  description             = "Control Tower API keys, Webhook secrets, and simulator tokens"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "app_secrets" {
  secret_id = aws_secretsmanager_secret.app_secrets.id
  secret_string = jsonencode({
    ADMIN_API_KEY        = "CHANGE_ME_ADMIN_KEY_32_CHARS_MINIMUM"
    API_KEY              = "CHANGE_ME_API_KEY_32_CHARS_MINIMUM"
    WEBHOOK_SECRET       = "CHANGE_ME_WEBHOOK_SECRET_32_CHARS_MIN"
    BRAND_API_KEYS       = "{\"brand_alpha\": 1, \"brand_beta\": 2}"
    CARRIER_API_KEYS     = "{\"carrier_alpha\": 1, \"carrier_beta\": 2}"
    TYPE_A_SIMULATOR_URL = "https://cargaexpress-simulator-a.onrender.com"
    TYPE_B_CARRIERS_URLS = "{\"SimCarrier A\": \"https://cargaexpress-simulator-b.mooo.com/carrier-a\"}"
    TYPE_C_CARRIERS_URLS = "{\"TransExpress Logistics\": \"https://cargaexpress-simulator-b.mooo.com/carrier-1\"}"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Airflow Core Secrets
resource "aws_secretsmanager_secret" "airflow" {
  name                    = "${var.project_name}/${var.environment}/airflow"
  description             = "Airflow Fernet key, webserver secret, and DB connection"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "airflow" {
  secret_id = aws_secretsmanager_secret.airflow.id
  secret_string = jsonencode({
    AIRFLOW__CORE__FERNET_KEY      = "46BKJoQYlPPOexq0OhDZnIlNepKFf87WFwLbfzqJZPo="
    AIRFLOW__WEBSERVER__SECRET_KEY = "CHANGE_ME_AIRFLOW_SECRET_KEY"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ------------------------------------------------------------------------------
# 3. IAM Execution Role (For ECS Agent to pull images, fetch secrets, push logs)
# ------------------------------------------------------------------------------
resource "aws_iam_role" "ecs_execution_role" {
  name = "${var.project_name}-${var.environment}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# Attach standard AWS managed execution policy
resource "aws_iam_role_policy_attachment" "ecs_execution_standard" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Inline policy to read Secrets Manager secrets and decrypt with KMS
resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.project_name}-${var.environment}-ecs-secrets-policy"
  description = "Allows ECS execution agent to retrieve secrets and decrypt via KMS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          aws_secretsmanager_secret.database.arn,
          aws_secretsmanager_secret.rabbitmq.arn,
          aws_secretsmanager_secret.app_secrets.arn,
          aws_secretsmanager_secret.airflow.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = [aws_kms_key.main.arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# ------------------------------------------------------------------------------
# 4. IAM Task Role (Runtime permissions for applications running in Fargate)
# ------------------------------------------------------------------------------
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name}-${var.environment}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# Runtime policy: access S3 Data Lake, publish metrics, run tasks (for Airflow/Spark)
resource "aws_iam_policy" "ecs_task_runtime" {
  name        = "${var.project_name}-${var.environment}-ecs-task-runtime-policy"
  description = "Allows runtime access to S3 Data Lake, CloudWatch, and ECS task execution"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowS3DataLake"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          var.s3_datalake_bucket_arn != "" ? var.s3_datalake_bucket_arn : "arn:aws:s3:::${var.project_name}-datalake-${var.environment}-*",
          var.s3_datalake_bucket_arn != "" ? "${var.s3_datalake_bucket_arn}/*" : "arn:aws:s3:::${var.project_name}-datalake-${var.environment}-*/*"
        ]
      },
      {
        Sid    = "AllowECSRunTaskForAirflow"
        Effect = "Allow"
        Action = [
          "ecs:RunTask",
          "ecs:StopTask",
          "ecs:DescribeTasks"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowPassRole"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          aws_iam_role.ecs_execution_role.arn,
          aws_iam_role.ecs_task_role.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_runtime" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_task_runtime.arn
}
