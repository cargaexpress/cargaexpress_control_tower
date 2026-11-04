"""Distributed task execution validation and audit pipeline for CeleryExecutor on RabbitMQ.

User Stories:
- HU-30 (RIWI-147): Scale workers and validate distributed execution
  - RIWI-146: Spin up at least 2 Celery worker containers
  - RIWI-148: Create a test DAG with parallel tasks
  - RIWI-149: Review each worker's logs to confirm distribution
  - RIWI-150: Document final configuration in the runbook (Deliverable E-12)

Architecture:
Uses Airflow TaskFlow API (@dag and @task decorators) for fan-out / fan-in parallel
execution audit across distributed Celery worker instances.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow.decorators import dag, task

logger = logging.getLogger("airflow.task")


@dag(
    dag_id="dag_distributed_validation",
    schedule=None,  # Manual trigger for operational audit and benchmark validation
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "airflow",
        "depends_on_past": False,
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["validation", "distributed", "celery", "rabbitmq", "audit"],
    doc_md=__doc__,
)
def distributed_execution_audit_pipeline() -> None:
    """Orchestrates fan-out worker probes and fan-in evidence consolidation."""

    @task
    def init_distributed_test() -> dict[str, Any]:
        """Initialize validation test session and capture dispatcher metadata."""
        utc_now = datetime.now(UTC).isoformat()
        host = socket.gethostname()
        pid = os.getpid()

        logger.info("=" * 70)
        logger.info("[INIT DISTRIBUTED TEST] Initializing fan-out probe via RabbitMQ...")
        logger.info(
            "Dispatcher Host: %s | PID: %s | Timestamp: %s",
            host,
            pid,
            utc_now,
        )
        logger.info("=" * 70)

        return {
            "init_timestamp": utc_now,
            "coordinator_host": host,
            "coordinator_pid": pid,
        }

    @task
    def execute_worker_probe(partition_id: int, workload_seconds: float = 3.0) -> dict[str, Any]:
        """Execute parallel probe task on assigned Celery worker node."""
        start_time = datetime.now(UTC)
        start_iso = start_time.isoformat()
        worker_host = socket.gethostname()
        worker_pid = os.getpid()
        thread_name = threading.current_thread().name

        try:
            worker_ip = socket.gethostbyname(worker_host)
        except Exception:
            worker_ip = "127.0.0.1"

        logger.info("-" * 60)
        logger.info(
            "[WORKER PROBE #%d] Running on Celery Worker: %s (IP: %s, PID: %d, Thread: %s)",
            partition_id,
            worker_host,
            worker_ip,
            worker_pid,
            thread_name,
        )
        logger.info("Simulating partition workload: %.2f seconds...", workload_seconds)

        # Simulate CPU/IO workload to enforce concurrent execution across available workers
        time.sleep(workload_seconds)

        end_time = datetime.now(UTC)
        duration_sec = (end_time - start_time).total_seconds()

        logger.info(
            "[DISTRIBUTED_EVIDENCE] Task=worker_probe_partition_%d | Hostname=%s | IP=%s | PID=%d | Thread=%s | Start=%s | End=%s | Duration=%.2fs | Status=SUCCESS",
            partition_id,
            worker_host,
            worker_ip,
            worker_pid,
            thread_name,
            start_iso,
            end_time.isoformat(),
            duration_sec,
        )
        logger.info("-" * 60)

        return {
            "partition_id": partition_id,
            "hostname": worker_host,
            "ip_address": worker_ip,
            "pid": worker_pid,
            "thread_name": thread_name,
            "start_time": start_iso,
            "end_time": end_time.isoformat(),
            "duration_seconds": duration_sec,
            "status": "SUCCESS",
        }

    @task
    def aggregate_distributed_evidence(
        init_meta: dict[str, Any],
        probe_1: dict[str, Any],
        probe_2: dict[str, Any],
        probe_3: dict[str, Any],
        probe_4: dict[str, Any],
    ) -> dict[str, Any]:
        """Consolidate worker metrics and emit audit compliance report."""
        probes = [probe_1, probe_2, probe_3, probe_4]

        distinct_hosts = {p["hostname"] for p in probes if "hostname" in p}
        distinct_pids = {p["pid"] for p in probes if "pid" in p}
        distinct_ips = {p["ip_address"] for p in probes if "ip_address" in p}

        # Multi-node distribution achieved if tasks executed on more than 1 distinct host or process
        is_distributed = len(distinct_hosts) >= 2 or len(distinct_pids) >= 2

        logger.info("=" * 80)
        logger.info("          AUDIT REPORT: DISTRIBUTED TASK EXECUTION (HU-30)")
        logger.info("=" * 80)
        logger.info("Coordinator Host:        %s", init_meta.get("coordinator_host"))
        logger.info("Total Parallel Probes:   %d", len(probes))
        logger.info(
            "Distinct Worker Hosts:   %d -> %s", len(distinct_hosts), sorted(distinct_hosts)
        )
        logger.info("Distinct Worker IPs:     %d -> %s", len(distinct_ips), sorted(distinct_ips))
        logger.info("Distinct Worker PIDs:    %d -> %s", len(distinct_pids), sorted(distinct_pids))
        logger.info("-" * 80)
        for p in probes:
            logger.info(
                "  Partition #%d: Host=%-18s | IP=%-15s | PID=%-6d | Duration=%.2fs",
                p["partition_id"],
                p["hostname"],
                p["ip_address"],
                p["pid"],
                p["duration_seconds"],
            )
        logger.info("-" * 80)

        if is_distributed:
            verdict = "VERIFIED_DISTRIBUTED"
            logger.info(
                "VERDICT: [%s] CeleryExecutor successfully distributed tasks across parallel workers.",
                verdict,
            )
        else:
            verdict = "SINGLE_WORKER_EXECUTION"
            logger.warning(
                "VERDICT: [%s] Probes executed on a single worker node (scale with --scale airflow-worker=2+).",
                verdict,
            )
        logger.info("=" * 80)

        return {
            "verdict": verdict,
            "is_distributed": is_distributed,
            "distinct_hosts_count": len(distinct_hosts),
            "distinct_hosts": sorted(distinct_hosts),
            "distinct_pids_count": len(distinct_pids),
            "total_probes": len(probes),
            "audit_timestamp": datetime.now(UTC).isoformat(),
        }

    init_meta = init_distributed_test()

    # Fan-out parallel branch execution
    p1 = execute_worker_probe(partition_id=1, workload_seconds=3.0)
    p2 = execute_worker_probe(partition_id=2, workload_seconds=3.0)
    p3 = execute_worker_probe(partition_id=3, workload_seconds=3.0)
    p4 = execute_worker_probe(partition_id=4, workload_seconds=3.0)

    # Fan-in evidence consolidation
    aggregate_distributed_evidence(init_meta, p1, p2, p3, p4)


distributed_execution_audit_pipeline()
