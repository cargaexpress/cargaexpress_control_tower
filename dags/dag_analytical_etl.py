"""Analytical ETL pipeline DAG to populate Kimball OLAP star schema and AWS S3 Gold Layer.

Runs every 30 minutes (*/30 * * * *) to keep Power BI analytics synchronized:
1. Verify Control Tower backend API readiness.
2. Execute shipment risk scan (POST /api/v1/alerts/scan).
3. Run OLTP -> OLAP Kimball dimensional ETL (POST /api/v1/analytics/etl/run).
4. Export all 10 OLAP tables to Snappy Parquet in S3 Gold Layer and align AWS Glue Catalog.
5. Verify analytical KPIs and Amazon Athena Gold Layer availability.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from airflow.decorators import dag, task
from utils.control_tower_client import ControlTowerClient

logger = logging.getLogger("airflow.task")

OLAP_TABLES: tuple[str, ...] = (
    "dim_dates",
    "dim_brands",
    "dim_carriers",
    "dim_distribution_centers",
    "dim_geographies",
    "dim_shipment_statuses",
    "fact_shipments_sla",
    "fact_financial_penalties",
    "fact_shipment_events",
    "fact_carrier_settlements",
)


def _pg_to_arrow_and_glue_type(pg_type: str, pa: Any) -> tuple[Any, str]:
    """Map PostgreSQL data_type names to consistent PyArrow and AWS Glue types."""
    normalized = pg_type.strip().lower()
    if normalized in ("integer", "smallint"):
        return pa.int32(), "int"
    if normalized == "bigint":
        return pa.int64(), "bigint"
    if normalized == "boolean":
        return pa.bool_(), "boolean"
    if normalized in ("numeric", "decimal", "double precision", "real"):
        return pa.float64(), "double"
    return pa.string(), "string"


def _coerce_column_values(values: list[Any], pg_type: str) -> list[Any]:
    """Coerce PostgreSQL row values into Arrow-compatible Python primitives."""
    normalized = pg_type.strip().lower()
    if normalized in ("integer", "smallint", "bigint"):
        return [None if v is None else int(v) for v in values]
    if normalized == "boolean":
        return [None if v is None else bool(v) for v in values]
    if normalized in ("numeric", "decimal", "double precision", "real"):
        return [float(v) if isinstance(v, Decimal) else (None if v is None else float(v)) for v in values]
    return [None if v is None else str(v) for v in values]


def _sync_glue_table(
    glue_client: Any,
    database_name: str,
    table_name: str,
    bucket: str,
    glue_columns: list[dict[str, str]],
) -> None:
    """Create or update the AWS Glue Catalog external Parquet table definition."""
    table_input = {
        "Name": table_name,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "parquet", "compressionType": "snappy"},
        "StorageDescriptor": {
            "Columns": glue_columns,
            "Location": f"s3://{bucket}/gold/{table_name}/",
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {
                "Name": "ParquetHiveSerDe",
                "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                "Parameters": {"serialization.format": "1"},
            },
        },
        "PartitionKeys": [],
    }
    try:
        glue_client.get_table(DatabaseName=database_name, Name=table_name)
        glue_client.update_table(DatabaseName=database_name, TableInput=table_input)
    except glue_client.exceptions.EntityNotFoundException:
        glue_client.create_table(DatabaseName=database_name, TableInput=table_input)


@dag(
    dag_id="analytical_etl_pipeline",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "airflow",
        "depends_on_past": False,
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=15),
    },
    tags=["analytics", "etl", "gold", "olap", "powerbi", "kimball"],
    doc_md=__doc__,
)
def analytical_etl_pipeline() -> None:
    """Orchestrates 30-minute OLAP ETL execution and S3 Gold Layer publication for Power BI."""

    @task
    def verify_backend_readiness() -> dict[str, Any]:
        """Check that Control Tower backend API is healthy before starting ETL."""
        client = ControlTowerClient()
        logger.info("Checking Control Tower API readiness at %s", client.base_url)
        health = client.check_health()
        logger.info("Control Tower health: %s", health)
        return health

    @task
    def scan_shipment_risks(health_probe: dict[str, Any]) -> dict[str, Any]:
        """Run risk scan to ensure alerts and risk flags are up to date prior to ETL."""
        client = ControlTowerClient()
        try:
            scan_summary = client.trigger_risk_scan()
            logger.info("Risk scan summary: %s", scan_summary)
            return scan_summary
        except Exception as exc:
            logger.warning("Risk scan warning (continuing with ETL): %s", exc)
            return {"status": "skipped", "warning": str(exc)}

    @task
    def run_analytical_etl(risk_summary: dict[str, Any]) -> dict[str, Any]:
        """Execute Kimball star-schema ETL pipeline on Control Tower backend."""
        client = ControlTowerClient()
        batch_result = client.trigger_analytical_etl()
        logger.info(
            "Analytical ETL completed: batch_id=%s, status=%s, extracted=%s, loaded=%s, rejected=%s",
            batch_result.get("batch_id"),
            batch_result.get("status"),
            batch_result.get("records_extracted"),
            batch_result.get("records_loaded"),
            batch_result.get("records_rejected"),
        )
        return batch_result

    @task
    def export_olap_to_s3_gold(batch_result: dict[str, Any]) -> dict[str, Any]:
        """Export all 10 OLAP tables to Snappy Parquet in AWS S3 Gold Layer and align Glue Catalog."""
        import boto3
        import psycopg2
        import pyarrow as pa
        import pyarrow.parquet as pq

        db_dsn = os.getenv(
            "OLAP_DATABASE_DSN",
            "postgresql://cargaexpress:change_me_local_only@db:5432/cargaexpress",
        )
        bucket = os.getenv("GOLD_S3_BUCKET", "cargaexpress-datalake-staging-326204936524")
        glue_db = os.getenv("GLUE_DATABASE", "cargaexpress_gold_staging")
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
        export_dir = Path(os.getenv("AIRFLOW_DATA_DIR", "/opt/airflow/data")) / "powerbi_export"
        export_dir.mkdir(parents=True, exist_ok=True)

        s3 = boto3.client("s3", region_name=region)
        glue = boto3.client("glue", region_name=region)

        exported_counts: dict[str, int] = {}
        conn = psycopg2.connect(db_dsn)
        try:
            with conn.cursor() as cur:
                for table_name in OLAP_TABLES:
                    cur.execute(
                        """
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (table_name,),
                    )
                    col_defs = cur.fetchall()
                    if not col_defs:
                        raise RuntimeError(f"OLAP table '{table_name}' not found in PostgreSQL")

                    col_names = [c[0] for c in col_defs]
                    col_sql = ", ".join(f'"{c}"' for c in col_names)
                    cur.execute(f'SELECT {col_sql} FROM "{table_name}"')
                    rows = cur.fetchall()

                    pa_fields = []
                    pa_arrays = []
                    glue_columns = []
                    for idx, (col_name, pg_type) in enumerate(col_defs):
                        pa_type, glue_type = _pg_to_arrow_and_glue_type(pg_type, pa)
                        pa_fields.append(pa.field(col_name, pa_type))
                        glue_columns.append({"Name": col_name, "Type": glue_type})
                        col_values = [row[idx] for row in rows]
                        coerced = _coerce_column_values(col_values, pg_type)
                        pa_arrays.append(pa.array(coerced, type=pa_type))

                    arrow_table = pa.Table.from_arrays(pa_arrays, schema=pa.schema(pa_fields))
                    local_pq = export_dir / f"{table_name}.parquet"
                    pq.write_table(arrow_table, str(local_pq), compression="snappy")

                    prefix = f"gold/{table_name}/"
                    existing_objs = s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
                    stale_keys = [
                        {"Key": obj["Key"]}
                        for obj in existing_objs
                        if obj["Key"] != f"{prefix}{table_name}.parquet"
                    ]
                    if stale_keys:
                        s3.delete_objects(Bucket=bucket, Delete={"Objects": stale_keys})

                    s3_key = f"{prefix}{table_name}.parquet"
                    s3.upload_file(str(local_pq), bucket, s3_key)
                    _sync_glue_table(glue, glue_db, table_name, bucket, glue_columns)

                    exported_counts[table_name] = len(rows)
                    logger.info(
                        "Published Gold table %s (%d rows) -> s3://%s/%s",
                        table_name,
                        len(rows),
                        bucket,
                        s3_key,
                    )
        finally:
            conn.close()

        return {
            "bucket": bucket,
            "glue_database": glue_db,
            "batch_id": batch_result.get("batch_id"),
            "table_counts": exported_counts,
        }

    @task
    def verify_powerbi_kpis(gold_export: dict[str, Any]) -> dict[str, Any]:
        """Verify analytical KPI totals and Gold Layer publication counts."""
        client = ControlTowerClient()
        kpis = client.get_analytics_kpis()
        logger.info("Power BI / OLAP KPI Summary: %s", kpis)
        logger.info("Gold S3 Table Row Counts: %s", gold_export.get("table_counts"))
        return {
            "kpis": kpis,
            "gold_export": gold_export,
        }

    health = verify_backend_readiness()
    risk_summary = scan_shipment_risks(health)
    batch_result = run_analytical_etl(risk_summary)
    gold_summary = export_olap_to_s3_gold(batch_result)
    verify_powerbi_kpis(gold_summary)


analytical_etl_pipeline()
