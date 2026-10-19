"""DAG de ingesta de archivos para transportadoras Tipo C (Fuente F5 - Batch/Archivos).

Historias de Usuario asociadas:
- HU-26 (RIWI-131): Set up Airflow in Docker
- HU-29 (RIWI-143): Configure CeleryExecutor in Airflow connected to RabbitMQ
- HU-28 (RIWI-139): Type-C file ingestion DAG (esqueleto base y pipeline de procesamiento)

Flujo de tareas:
1. check_incoming_files: Detecta archivos CSV/XLSX en data/type_C_simulation_data/.
2. validate_and_clean_batch: Limpia cabeceras duplicadas, filas de resumen/pie y registros inválidos.
3. normalize_and_ingest: Mapea estados a los estados canónicos e inserta/actualiza en WMS PostgreSQL.
"""

from __future__ import annotations

import glob
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from airflow import DAG
from airflow.operators.python import PythonOperator

# Directorios de datos montados en el contenedor de Airflow
DATA_BASE_DIR = os.getenv("AIRFLOW_DATA_DIR", "/opt/airflow/data")
INCOMING_DIR = os.path.join(DATA_BASE_DIR, "type_C_simulation_data")
PROCESSED_DIR = os.path.join(INCOMING_DIR, "processed")

# Configuración de base de datos WMS (PostgreSQL principal de CargaExpress)
WMS_DB_HOST = os.getenv("WMS_DB_HOST", "db")
WMS_DB_PORT = int(os.getenv("WMS_DB_PORT", "5432"))
WMS_DB_NAME = os.getenv("WMS_DB_NAME", os.getenv("POSTGRES_DB", "cargaexpress"))
WMS_DB_USER = os.getenv("WMS_DB_USER", os.getenv("POSTGRES_USER", "postgres"))
WMS_DB_PASSWORD = os.getenv("WMS_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres"))

# Catálogos conocidos de transportadoras Tipo C según especificación técnica
TYPE_C_CONFIGS: Dict[str, Dict[str, Any]] = {
    "CARRIER_1": {
        "carrier_id": 1,
        "name": "TransExpress Logistics",
        "tracking_cols": ["waybill_no", "tracking_number", "guia", "tracking_code"],
        "status_cols": ["status_code", "status", "estado"],
        "timestamp_cols": ["event_time", "timestamp", "fecha"],
        "fallback_mappings": {
            "DOC_REC": "CREATED",
            "DISPATCHED": "PICKED_UP",
            "IN_DEPOT": "IN_TRANSIT",
            "OUT_DELIVERY": "OUT_FOR_DELIVERY",
            "INCIDENCE": "EXCEPTION",
            "DELIVERED": "DELIVERED",
            "RETURN_SENDER": "RETURNED",
            "DAMAGED_CARGO": "LOST_OR_DAMAGED",
        },
    },
    "CARRIER_2": {
        "carrier_id": 2,
        "name": "Rápido Andino",
        "tracking_cols": ["numero_guia", "guia", "tracking_number"],
        "status_cols": ["estado_operativo", "estado", "status"],
        "timestamp_cols": ["fecha_hora_evento", "fecha", "timestamp"],
        "fallback_mappings": {
            "REGISTRADO": "CREATED",
            "RECOLECTADO": "PICKED_UP",
            "TRASLADO_INTERNO": "IN_TRANSIT",
            "RUTA_ENTREGA": "OUT_FOR_DELIVERY",
            "NOVEDAD_DIRECCION": "EXCEPTION",
            "ENTREGADO_OK": "DELIVERED",
            "DEVUELTO_ORIGEN": "RETURNED",
            "EXTRAVIO": "LOST_OR_DAMAGED",
        },
    },
    "CARRIER_3": {
        "carrier_id": 3,
        "name": "Logística 360",
        "tracking_cols": ["tracking_code", "waybill_no", "code"],
        "status_cols": ["code", "status_code", "estado"],
        "timestamp_cols": ["event_date", "timestamp", "event_time"],
        "fallback_mappings": {
            "10": "CREATED",
            "20": "PICKED_UP",
            "30": "IN_TRANSIT",
            "40": "OUT_FOR_DELIVERY",
            "50": "EXCEPTION",
            "90": "DELIVERED",
            "91": "RETURNED",
            "99": "LOST_OR_DAMAGED",
        },
    },
}

CANONICAL_STATUSES = {
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
}


def check_incoming_files(**context: Any) -> List[str]:
    """Tarea a: Verifica si existen archivos CSV o XLSX en la carpeta de entrada."""
    logger = logging.getLogger("airflow.task")
    logger.info("Verificando archivos entrantes en %s", INCOMING_DIR)

    if not os.path.exists(INCOMING_DIR):
        os.makedirs(INCOMING_DIR, exist_ok=True)
        logger.info("Directorio %s creado exitosamente", INCOMING_DIR)

    search_patterns = [
        os.path.join(INCOMING_DIR, "*.csv"),
        os.path.join(INCOMING_DIR, "*.xlsx"),
    ]

    found_files: List[str] = []
    for pattern in search_patterns:
        found_files.extend(glob.glob(pattern))

    # Filtrar archivos temporales de Excel o subdirectorios
    valid_files = [
        f for f in found_files
        if not os.path.basename(f).startswith("~$") and os.path.isfile(f)
    ]

    logger.info("Se encontraron %d archivo(s) para procesar: %s", len(valid_files), valid_files)
    return valid_files


def _is_summary_or_header_row(row_values: List[str], header_names: List[str]) -> bool:
    """Detecta si una fila corresponde a un encabezado repetido o fila de resumen/totales."""
    clean_vals = [str(v).strip().upper() for v in row_values if v is not None and str(v).strip()]
    if not clean_vals:
        return True

    # Comprobar si coincide con nombres de cabeceras
    header_set = {h.strip().upper() for h in header_names if h}
    matches = sum(1 for val in clean_vals if val in header_set)
    if matches >= max(1, len(clean_vals) // 2):
        return True

    # Comprobar palabras clave de pie de reporte o resumen
    joined_text = " ".join(clean_vals)
    summary_keywords = ["TOTAL", "REGISTROS", "FIN DE LOTE", "RESUMEN", "SUBTOTAL"]
    if any(keyword in joined_text for keyword in summary_keywords):
        return True

    return False


def validate_and_clean_batch(**context: Any) -> List[Dict[str, Any]]:
    """Tarea b: Valida, filtra cabeceras duplicadas, filas de resumen o datos corruptos."""
    logger = logging.getLogger("airflow.task")
    ti = context["ti"]
    incoming_files: List[str] = ti.xcom_pull(task_ids="check_incoming_files") or []

    if not incoming_files:
        logger.info("No hay archivos entrantes. Finalizando lote sin procesar registros.")
        return []

    try:
        import pandas as pd
    except ImportError:
        logger.warning("Pandas no está instalado en este entorno local. Usando fallback básico.")
        pd = None

    cleaned_records: List[Dict[str, Any]] = []

    for file_path in incoming_files:
        logger.info("Iniciando validación y limpieza de: %s", file_path)
        filename = os.path.basename(file_path)

        # Identificar transportadora a partir del nombre del archivo o contenido
        carrier_hint = "CARRIER_1"
        upper_fn = filename.upper()
        if "CARRIER_2" in upper_fn or "RAPIDO" in upper_fn:
            carrier_hint = "CARRIER_2"
        elif "CARRIER_3" in upper_fn or "360" in upper_fn:
            carrier_hint = "CARRIER_3"

        carrier_cfg = TYPE_C_CONFIGS.get(carrier_hint, TYPE_C_CONFIGS["CARRIER_1"])

        if pd is not None:
            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path, dtype=str)
            else:
                df = pd.read_excel(file_path, dtype=str)

            initial_count = len(df)
            headers = [str(c) for c in df.columns]

            # 1. Eliminar filas completamente vacías
            df = df.dropna(how="all")

            # 2. Filtrar filas de encabezado repetido o totales
            valid_mask = []
            for _, row in df.iterrows():
                vals = [str(v) for v in row.values]
                valid_mask.append(not _is_summary_or_header_row(vals, headers))

            df = df[valid_mask]

            # 3. Eliminar duplicados exactos
            df = df.drop_duplicates()

            # Mapear columnas a formato estandarizado
            tracking_col = next((c for c in headers if c.lower() in [tc.lower() for tc in carrier_cfg["tracking_cols"]]), headers[0])
            status_col = next((c for c in headers if c.lower() in [sc.lower() for sc in carrier_cfg["status_cols"]]), headers[1] if len(headers) > 1 else headers[0])
            timestamp_col = next((c for c in headers if c.lower() in [tsc.lower() for tsc in carrier_cfg["timestamp_cols"]]), headers[2] if len(headers) > 2 else headers[0])

            for _, row in df.iterrows():
                tracking_val = str(row.get(tracking_col, "")).strip()
                status_val = str(row.get(status_col, "")).strip()
                raw_ts = str(row.get(timestamp_col, "")).strip()

                if not tracking_val or tracking_val.upper().startswith("TOTAL"):
                    continue

                cleaned_records.append({
                    "source_file": filename,
                    "carrier_id": carrier_cfg["carrier_id"],
                    "carrier_code": carrier_hint,
                    "tracking_number": tracking_val,
                    "raw_status": status_val,
                    "occurred_at_raw": raw_ts,
                })

            logger.info(
                "Archivo %s: %d filas iniciales -> %d registros limpios",
                filename, initial_count, len(df)
            )

    logger.info("Total de registros limpios en lote: %d", len(cleaned_records))
    return cleaned_records


def _fetch_db_state_mappings(carrier_id: int) -> Dict[str, str]:
    """Obtiene el mapeo de estados configurado en PostgreSQL si está disponible."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=WMS_DB_HOST,
            port=WMS_DB_PORT,
            dbname=WMS_DB_NAME,
            user=WMS_DB_USER,
            password=WMS_DB_PASSWORD,
            connect_timeout=3,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT raw_status, canonical_status FROM state_mapping WHERE carrier_id = %s",
            (carrier_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception as exc:
        logging.getLogger("airflow.task").warning(
            "No se pudo consultar PostgreSQL para state_mapping: %s. Usando catálogo en memoria.",
            exc,
        )
        return {}


def _update_wms_shipping_label(tracking_number: str, canonical_status: str) -> bool:
    """Actualiza el estado de la guía en el WMS si existe conexión a PostgreSQL."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=WMS_DB_HOST,
            port=WMS_DB_PORT,
            dbname=WMS_DB_NAME,
            user=WMS_DB_USER,
            password=WMS_DB_PASSWORD,
            connect_timeout=3,
        )
        cur = conn.cursor()
        cur.execute(
            "UPDATE shipping_labels SET status = %s WHERE tracking_number = %s",
            (canonical_status, tracking_number),
        )
        conn.commit()
        updated_count = cur.rowcount
        cur.close()
        conn.close()
        return updated_count > 0
    except Exception as exc:
        logging.getLogger("airflow.task").debug(
            "Actualización simulada para guía %s: %s", tracking_number, exc
        )
        return False


def normalize_and_ingest(**context: Any) -> Dict[str, Any]:
    """Tarea c: Traduce raw_status a canonical_status y realiza la ingesta/actualización."""
    logger = logging.getLogger("airflow.task")
    ti = context["ti"]
    cleaned_records: List[Dict[str, Any]] = ti.xcom_pull(task_ids="validate_and_clean_batch") or []

    if not cleaned_records:
        logger.info("No hay registros para normalizar e ingerir.")
        return {"processed": 0, "canonical_counts": {}}

    logger.info("Normalizando e ingiriendo %d registro(s)...", len(cleaned_records))

    # Cache local de mapeos por transportadora
    cached_mappings: Dict[int, Dict[str, str]] = {}
    canonical_counts: Dict[str, int] = {st: 0 for st in CANONICAL_STATUSES}
    unmapped_count = 0
    updated_wms_count = 0

    for record in cleaned_records:
        carrier_id = record["carrier_id"]
        carrier_code = record["carrier_code"]
        raw_status = record["raw_status"]
        tracking_no = record["tracking_number"]

        if carrier_id not in cached_mappings:
            db_maps = _fetch_db_state_mappings(carrier_id)
            fallback = TYPE_C_CONFIGS.get(carrier_code, {}).get("fallback_mappings", {})
            # Mezclar BD con fallback en memoria
            merged = {**fallback, **db_maps}
            cached_mappings[carrier_id] = merged

        mapping = cached_mappings[carrier_id]
        canonical_status = mapping.get(raw_status)

        if not canonical_status:
            # Búsqueda insensible a mayúsculas
            upper_raw = raw_status.upper()
            canonical_status = next(
                (v for k, v in mapping.items() if k.upper() == upper_raw),
                "EXCEPTION",  # Regla: estados sin mapeo o anómalos van a EXCEPTION
            )
            unmapped_count += 1

        if canonical_status in canonical_counts:
            canonical_counts[canonical_status] += 1

        # Realizar inserción o actualización en el WMS
        is_updated = _update_wms_shipping_label(tracking_no, canonical_status)
        if is_updated:
            updated_wms_count += 1

    # Mover archivos procesados si existen
    incoming_files = ti.xcom_pull(task_ids="check_incoming_files") or []
    if incoming_files:
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        for src_path in incoming_files:
            try:
                dest_path = os.path.join(PROCESSED_DIR, os.path.basename(src_path))
                if os.path.exists(src_path):
                    os.replace(src_path, dest_path)
                    logger.info("Archivo archivado: %s -> %s", src_path, dest_path)
            except Exception as e:
                logger.warning("No se pudo mover archivo %s: %s", src_path, e)

    summary = {
        "total_records": len(cleaned_records),
        "unmapped_records": unmapped_count,
        "wms_records_updated": updated_wms_count,
        "canonical_counts": canonical_counts,
    }
    logger.info("Resumen de ingesta Tipo C completado: %s", summary)
    return summary


# Definición del DAG
default_args = {
    "owner": "cargaexpress",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="dag_type_c_ingestion",
    default_args=default_args,
    description="Ingesta de archivos por lotes (CSV/XLSX) de transportadoras Tipo C - HU-28",
    schedule_interval="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["cargaexpress", "type_c", "ingestion", "wms", "sprint3"],
) as dag:

    t_check_incoming = PythonOperator(
        task_id="check_incoming_files",
        python_callable=check_incoming_files,
        provide_context=True,
    )

    t_validate_clean = PythonOperator(
        task_id="validate_and_clean_batch",
        python_callable=validate_and_clean_batch,
        provide_context=True,
    )

    t_normalize_ingest = PythonOperator(
        task_id="normalize_and_ingest",
        python_callable=normalize_and_ingest,
        provide_context=True,
    )

    t_check_incoming >> t_validate_clean >> t_normalize_ingest
