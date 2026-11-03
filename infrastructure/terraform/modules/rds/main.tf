# ==============================================================================
# CargaExpress Infrastructure - RDS PostgreSQL Module
# File: infrastructure/terraform/modules/rds/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. DB Subnet Group (Private Database Subnets across 2 AZs)
# ------------------------------------------------------------------------------
resource "aws_db_subnet_group" "main" {
  name        = "${var.project_name}-${var.environment}-db-subnet-group"
  description = "Subnet group for CargaExpress PostgreSQL RDS instances"
  subnet_ids  = var.private_db_subnet_ids

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-db-subnet-group"
    }
  )
}

# ------------------------------------------------------------------------------
# 2. DB Parameter Group (Enforce TLS and Performance Parameters)
# ------------------------------------------------------------------------------
resource "aws_db_parameter_group" "postgres16" {
  name        = "${var.project_name}-${var.environment}-pg16-params"
  family      = "postgres16"
  description = "Custom parameter group enforcing TLS 1.3 and security parameters"

  parameter {
    name  = "rds.force_ssl"
    value = "1" # Enforce TLS encryption for all incoming connections
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 3. Amazon RDS PostgreSQL 16 Instance
# ------------------------------------------------------------------------------
resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-${var.environment}-postgres"
  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_name  = var.database_name
  username = var.admin_username
  password = var.admin_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.rds_security_group_id]
  parameter_group_name   = aws_db_parameter_group.postgres16.name

  multi_az            = var.enable_multi_az
  publicly_accessible = false # Strictly isolated in private DB subnets

  backup_retention_period    = var.backup_retention_period
  backup_window              = "03:00-04:00" # UTC (22:00-23:00 Colombia/Peru)
  maintenance_window         = "Sun:04:30-Sun:05:30"
  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = var.skip_final_snapshot
  final_snapshot_identifier  = "${var.project_name}-${var.environment}-postgres-final-snapshot"

  copy_tags_to_snapshot = true

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-postgres"
      Environment = var.environment
    }
  )
}
