# ==============================================================================
# CargaExpress Infrastructure - S3 Data Lake Module
# File: infrastructure/terraform/modules/s3_datalake/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Main S3 Data Lake Bucket
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "datalake" {
  bucket        = "${var.project_name}-datalake-${var.environment}-${var.aws_account_id}"
  force_destroy = false

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-datalake-${var.environment}"
      Environment = var.environment
      DataTier    = "MultiTierDataLake"
    }
  )
}

# Enforce KMS Server-Side Encryption (SSE-KMS)
resource "aws_s3_bucket_server_side_encryption_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# Block all Public Access (Security Best Practice)
resource "aws_s3_bucket_public_access_block" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 Versioning for Auditability and Accidental Deletion Protection
resource "aws_s3_bucket_versioning" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Data Lake Lifecycle Policies (Landing, Bronze, Silver, Gold)
resource "aws_s3_bucket_lifecycle_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  # 1. Landing layer: Raw incoming files transition to Infrequent Access after 60 days
  rule {
    id     = "landing-lifecycle"
    status = "Enabled"

    filter {
      prefix = "landing/"
    }

    transition {
      days          = 60
      storage_class = "STANDARD_IA"
    }

    expiration {
      days = 365 # Retain landing files for 1 year
    }
  }

  # 2. Bronze layer: Raw immutable data transition to Glacier Flexible Retrieval after 90 days
  rule {
    id     = "bronze-lifecycle"
    status = "Enabled"

    filter {
      prefix = "bronze/"
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 180
      storage_class = "GLACIER"
    }
  }

  # 3. Noncurrent version cleanup after 90 days
  rule {
    id     = "cleanup-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# ------------------------------------------------------------------------------
# 2. S3 Bucket Prefixes (Landing, Bronze, Silver, Gold)
# ------------------------------------------------------------------------------
resource "aws_s3_object" "landing_prefix" {
  bucket  = aws_s3_bucket.datalake.id
  key     = "landing/"
  content = ""
}

resource "aws_s3_object" "bronze_prefix" {
  bucket  = aws_s3_bucket.datalake.id
  key     = "bronze/"
  content = ""
}

resource "aws_s3_object" "silver_prefix" {
  bucket  = aws_s3_bucket.datalake.id
  key     = "silver/"
  content = ""
}

resource "aws_s3_object" "gold_prefix" {
  bucket  = aws_s3_bucket.datalake.id
  key     = "gold/"
  content = ""
}

# ------------------------------------------------------------------------------
# 3. S3 Bucket for Athena Query Results
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "athena_results" {
  bucket        = "${var.project_name}-athena-results-${var.environment}-${var.aws_account_id}"
  force_destroy = false

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-athena-results-${var.environment}"
    }
  )
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Expire Athena temporary query results after 30 days
resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "expire-athena-query-results"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}

# ------------------------------------------------------------------------------
# 4. Strict TLS Encryption-in-Transit Bucket Policies (Deny Insecure HTTP)
# ------------------------------------------------------------------------------
resource "aws_s3_bucket_policy" "datalake_tls" {
  bucket = aws_s3_bucket.datalake.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceTLSRequestsOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.datalake.arn,
          "${aws_s3_bucket.datalake.arn}/*"
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

resource "aws_s3_bucket_policy" "athena_results_tls" {
  bucket = aws_s3_bucket.athena_results.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceTLSRequestsOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*"
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
