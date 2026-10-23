"""Periodic pull polling DAG for Type B carriers (Source F4).

Airflow User Stories:
- HU-27 (RIWI-135): Pull polling DAG for type-B carriers
  - RIWI-136: Schedule interval every 30 minutes (*/30 * * * *)
  - RIWI-137: Reuses Type B connector service from HU-21
  - RIWI-138: Configure retries with exponential backoff and rate limit resilience

Architecture:
Uses Airflow TaskFlow API (@dag and @task decorators).
Triggers Control Tower Type B polling connector (POST /api/v1/sync/type-b) which queries
simulated carrier REST APIs, respects rate limits with backoff, normalizes tracking statuses
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
    dag_id="type_b_pull_polling",
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
    tags=["ingestion", "type-b", "pull", "polling"],
    doc_md=__doc__,
)
def type_b_pull_polling_pipeline() -> None:
    """Orchestrates periodic polling of all Type B REST carrier endpoints."""

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
    def poll_type_b_carriers(health_probe: dict[str, Any]) -> dict[str, Any]:
        """Trigger pull sync for all Type B carriers via connector service."""
        client = ControlTowerClient()
        logger.info("Starting scheduled Type B polling across all registered carriers...")

        response = client.trigger_type_b_sync()
        status = response.get("status", "unknown")
        results = response.get("results", [])

        logger.info(
            "Type B sync completed with status '%s'. Carrier responses: %d",
            status,
            len(results),
        )

        for item in results:
            carrier = item.get("carrier")
            total = item.get("total_fetched", 0)
            normalized = item.get("normalized", 0)
            anomalies = item.get("anomalies", 0)
            errors = item.get("errors", 0)
            rate_limits = item.get("rate_limits_encountered", 0)
            sync_status = item.get("sync_status", "unknown")

            logger.info(
                "Carrier '%s': status=%s, fetched=%d, normalized=%d, anomalies=%d, rate_limits=%d, errors=%d",
                carrier,
                sync_status,
                total,
                normalized,
                anomalies,
                rate_limits,
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
        total_rate_limits = sum(int(r.get("rate_limits_encountered", 0)) for r in results)

        metrics = {
            "carriers_polled": len(results),
            "total_fetched": total_fetched,
            "total_normalized": total_normalized,
            "total_anomalies": total_anomalies,
            "total_errors": total_errors,
            "total_rate_limits": total_rate_limits,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info("Type B Polling Aggregated Metrics: %s", metrics)

        # Log alerts for anomalies or errors if any
        if total_errors > 0:
            logger.warning(
                "Identified %d error(s) during Type B polling. Review worker logs.", total_errors
            )
        if total_anomalies > 0:
            logger.info(
                "Identified %d state transition anomalies (RN-02 recorded).", total_anomalies
            )

        return metrics

    health = verify_backend_readiness()
    sync_summary = poll_type_b_carriers(health)
    evaluate_polling_metrics(sync_summary)


type_b_pull_polling_pipeline()
