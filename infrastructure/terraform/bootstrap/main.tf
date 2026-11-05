# ==============================================================================
# CargaExpress Infrastructure - Terraform State Remote S3 Backend Bootstrap
# File: infrastructure/terraform/bootstrap/main.tf
# ==============================================================================
# This root module provisions the foundational remote state backend resources:
# 1. Encrypted, versioned Amazon S3 Bucket for terraform.tfstate
# 2. DynamoDB Table for concurrent state locking
#
# IMPORTANT: This must be applied ONCE locally before configuring `backend "s3"`
# in environments/staging and environments/production.
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
      Project   = "cargaexpress"
      ManagedBy = "Terraform"
      Purpose   = "TerraformRemoteState"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id  = var.aws_account_id != null && var.aws_account_id != "" ? var.aws_account_id : data.aws_caller_identity.current.account_id
  bucket_name = "cargaexpress-tfstate-${var.aws_region}-${local.account_id}"
}

# ------------------------------------------------------------------------------
# 1. S3 Remote State Bucket
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "terraform_state" {
  bucket        = local.bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = local.bucket_name
  }
}

# Enforce Object Versioning (State History & Recovery)
resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Customer Managed Key (CMK) for Terraform State Encryption
resource "aws_kms_key" "terraform_state" {
  description             = "KMS CMK for Terraform Remote State S3 Bucket and DynamoDB"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name    = "cargaexpress-tfstate-kms"
    Purpose = "TerraformRemoteState"
  }
}

resource "aws_kms_alias" "terraform_state" {
  name          = "alias/cargaexpress-tfstate"
  target_key_id = aws_kms_key.terraform_state.key_id
}

# Enforce Server-Side Encryption with Customer Managed Key (CMK)
resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.terraform_state.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# Block all Public Access
resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enforce TLS transport only
resource "aws_s3_bucket_policy" "terraform_state_tls" {
  bucket = aws_s3_bucket.terraform_state.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceTLSRequestsOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# 2. DynamoDB Table for State Locking
# ------------------------------------------------------------------------------
resource "aws_dynamodb_table" "terraform_locks" {
  name         = "cargaexpress-tfstate-locks"
  billing_mode = "PAY_PER_REQUEST" # Serverless on-demand billing: $0 when idle
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.terraform_state.arn
  }

  tags = {
    Name = "cargaexpress-tfstate-locks"
  }
}
