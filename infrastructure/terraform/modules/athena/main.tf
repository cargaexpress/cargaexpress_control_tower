# ==============================================================================
# CargaExpress Infrastructure - Athena & Glue Catalog Module
# File: infrastructure/terraform/modules/athena/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. AWS Glue Data Catalog Database (Gold Layer)
# ------------------------------------------------------------------------------
resource "aws_glue_catalog_database" "gold" {
  name        = "${var.project_name}_gold_${var.environment}"
  description = "Glue Catalog database for CargaExpress analytical Gold dimensional model"

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 2. Amazon Athena Workgroup
# ------------------------------------------------------------------------------
resource "aws_athena_workgroup" "analytics" {
  name        = "${var.project_name}-analytics-${var.environment}"
  description = "Athena workgroup for CargaExpress BI and ad-hoc analytical queries"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 10737418240 # 10 GB scan safeguard (~$0.05 max per query)

    result_configuration {
      output_location = "s3://${var.athena_results_bucket_name}/queries/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = var.kms_key_arn
      }
    }
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 3. Glue Catalog Tables for Analytical Star Schema (Gold Layer)
# ------------------------------------------------------------------------------

# 3.1 Fact Table: Shipments SLA (fact_shipments_sla)
resource "aws_glue_catalog_table" "fact_shipments_sla" {
  name          = "fact_shipments_sla"
  database_name = aws_glue_catalog_database.gold.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"  = "parquet"
    "compressionType" = "snappy"
    "typeOfData"      = "file"
  }

  storage_descriptor {
    location      = "s3://${var.datalake_bucket_name}/gold/fact_shipments_sla/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "ParquetHiveSerDe"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "fact_shipment_key"
      type = "bigint"
    }
    columns {
      name = "shipment_id"
      type = "bigint"
    }
    columns {
      name = "tracking_number"
      type = "string"
    }
    columns {
      name = "order_id"
      type = "bigint"
    }
    columns {
      name = "date_key"
      type = "int"
    }
    columns {
      name = "dim_brand_key"
      type = "bigint"
    }
    columns {
      name = "dim_carrier_key"
      type = "bigint"
    }
    columns {
      name = "dim_center_key"
      type = "bigint"
    }
    columns {
      name = "dim_status_key"
      type = "bigint"
    }
    columns {
      name = "dim_geography_key"
      type = "bigint"
    }
    columns {
      name = "freight_amount"
      type = "decimal(12,2)"
    }
    columns {
      name = "promised_hours"
      type = "int"
    }
    columns {
      name = "transit_business_hours"
      type = "decimal(10,2)"
    }
    columns {
      name = "delay_business_hours"
      type = "decimal(10,2)"
    }
    columns {
      name = "penalty_amount"
      type = "decimal(12,2)"
    }
    columns {
      name = "is_delivered"
      type = "boolean"
    }
    columns {
      name = "is_compliant"
      type = "boolean"
    }
    columns {
      name = "is_breached"
      type = "boolean"
    }
    columns {
      name = "is_in_risk"
      type = "boolean"
    }
    columns {
      name = "etl_batch_id"
      type = "bigint"
    }
    columns {
      name = "source_system"
      type = "string"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
}

# 3.2 Fact Table: Financial Penalties (fact_financial_penalties)
resource "aws_glue_catalog_table" "fact_financial_penalties" {
  name          = "fact_financial_penalties"
  database_name = aws_glue_catalog_database.gold.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"  = "parquet"
    "compressionType" = "snappy"
  }

  storage_descriptor {
    location      = "s3://${var.datalake_bucket_name}/gold/fact_financial_penalties/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "ParquetHiveSerDe"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "fact_penalty_key"
      type = "bigint"
    }
    columns {
      name = "shipment_id"
      type = "bigint"
    }
    columns {
      name = "date_key"
      type = "int"
    }
    columns {
      name = "dim_carrier_key"
      type = "bigint"
    }
    columns {
      name = "responsible_party"
      type = "string"
    }
    columns {
      name = "penalty_level"
      type = "string"
    }
    columns {
      name = "freight_amount"
      type = "decimal(12,2)"
    }
    columns {
      name = "penalty_percentage"
      type = "decimal(5,4)"
    }
    columns {
      name = "base_penalty_amount"
      type = "decimal(12,2)"
    }
    columns {
      name = "max_cap_percentage"
      type = "decimal(5,4)"
    }
    columns {
      name = "final_penalty_amount"
      type = "decimal(12,2)"
    }
    columns {
      name = "delay_business_days"
      type = "decimal(8,2)"
    }
    columns {
      name = "approval_status"
      type = "string"
    }
    columns {
      name = "etl_batch_id"
      type = "bigint"
    }
    columns {
      name = "source_system"
      type = "string"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
}

# 3.3 Dimension Table: Carriers (dim_carriers)
resource "aws_glue_catalog_table" "dim_carriers" {
  name          = "dim_carriers"
  database_name = aws_glue_catalog_database.gold.name
  table_type    = "EXTERNAL_TABLE"

  storage_descriptor {
    location      = "s3://${var.datalake_bucket_name}/gold/dim_carriers/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "ParquetHiveSerDe"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "dim_carrier_key"
      type = "bigint"
    }
    columns {
      name = "natural_carrier_id"
      type = "int"
    }
    columns {
      name = "name"
      type = "string"
    }
    columns {
      name = "carrier_type"
      type = "string"
    }
    columns {
      name = "is_active"
      type = "boolean"
    }
  }
}

# 3.4 Dimension Table: Brands (dim_brands)
resource "aws_glue_catalog_table" "dim_brands" {
  name          = "dim_brands"
  database_name = aws_glue_catalog_database.gold.name
  table_type    = "EXTERNAL_TABLE"

  storage_descriptor {
    location      = "s3://${var.datalake_bucket_name}/gold/dim_brands/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "ParquetHiveSerDe"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "dim_brand_key"
      type = "bigint"
    }
    columns {
      name = "natural_brand_id"
      type = "int"
    }
    columns {
      name = "name"
      type = "string"
    }
    columns {
      name = "code"
      type = "string"
    }
  }
}
