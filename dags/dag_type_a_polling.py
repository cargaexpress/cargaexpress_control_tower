"""Periodic pull polling DAG for Type A carrier simulator (Source F3 / Receiver Extractor).

Airflow User Stories:
- F3 Webhook Simulator Polling Pipeline:
  - Schedule interval every 30 minutes (*/30 * * * *)
  - Reuses Type A connector service and NormalizationService
  - Configure retries with exponential backoff and rate limit resilience

Architecture:
Uses Airflow TaskFlow API (@dag and @task decorators).
Triggers Control Tower Type A polling connector (POST /api/v1/sync/type-a) which queries
the Type A Webhook Simulator Receiver exports/events API, normalizes tracking statuses
to the 8 canonical states, and updates WMS database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from airflow.decorators import dag, task
from utils.control_tower_client import ControlTowerClient

logger = logging.getLogger("airflow.task")


@dag(
    dag_id="type_a_pull_polling",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "airflow",
        "depends_on_past": False,
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=20),
        "execution_timeout": timedelta(minutes=15),
    },
    tags=["ingestion", "type-a", "pull", "polling", "simulator"],
    doc_md=__doc__,
)
def type_a_pull_polling_pipeline() -> None:
    """Orchestrates periodic polling of Type A Webhook Simulator events."""

    @task
    def verify_backend_readiness() -> dict[str, Any]:
        """Check that Control Tower backend API is healthy before polling."""
        client = ControlTowerClient()
        logger.info("Performing readiness probe on Control Tower API: %s", client.base_url)
        try:
            health = client.check_health()
            logger.info("Control Tower health status: %s", health.get("status", "unknown"))
            return health
        except Exception as exc:
            logger.warning(
                "Health check probe failed or backend warming up: %s. Proceeding with sync attempt.",
                exc,
            )
            return {"status": "unverified", "warning": str(exc)}

    @task
    def poll_type_a_carriers(health_probe: dict[str, Any]) -> dict[str, Any]:
        """Trigger pull sync for Type A carriers via connector service."""
        client = ControlTowerClient()
        logger.info("Starting scheduled Type A polling from simulator receiver...")

        response = client.trigger_type_a_sync()
        status = response.get("status", "unknown")
        results = response.get("results", [])

        logger.info(
            "Type A sync completed with status '%s'. Carrier responses: %d",
            status,
            len(results),
        )

        for item in results:
            carrier = item.get("carrier")
            total = item.get("total_fetched", 0)
            normalized = item.get("normalized", 0)
            anomalies = item.get("anomalies", 0)
            errors = item.get("errors", 0)
            sync_status = item.get("sync_status", "unknown")

            logger.info(
                "Carrier '%s': status=%s, fetched=%d, normalized=%d, anomalies=%d, errors=%d",
                carrier,
                sync_status,
                total,
                normalized,
                anomalies,
                errors,
            )

        return response

    @task
    def evaluate_polling_metrics(summary: dict[str, Any]) -> dict[str, Any]:
        """Audit polling execution metrics and ensure SLA compliance."""
        results = summary.get("results", [])
        total_fetched = sum(int(r.get("total_fetched", 0)) for r in results)
        total_normalized = sum(int(r.get("normalized", 0)) for r in results)
        total_anomalies = sum(int(r.get("anomalies", 0)) for r in results)
        total_errors = sum(int(r.get("errors", 0)) for r in results)

        metrics = {
            "carriers_polled": len(results),
            "total_fetched": total_fetched,
            "total_normalized": total_normalized,
            "total_anomalies": total_anomalies,
            "total_errors": total_errors,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info("Type A Polling Aggregated Metrics: %s", metrics)

        if total_errors > 0:
            logger.warning(
                "Identified %d error(s) during Type A polling. Review worker logs.", total_errors
            )
        if total_anomalies > 0:
            logger.info(
                "Identified %d state transition anomalies (RN-02 recorded).", total_anomalies
            )

        return metrics

    health = verify_backend_readiness()
    sync_summary = poll_type_a_carriers(health)
    evaluate_polling_metrics(sync_summary)


type_a_pull_polling_pipeline()
