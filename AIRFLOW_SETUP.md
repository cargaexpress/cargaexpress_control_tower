# Airflow Deployment and Operations Guide with CeleryExecutor and RabbitMQ

This document details the architecture, configuration, and operational runbook for the distributed orchestration environment of **CargaExpress**, covering:
- Setting up Airflow in Docker with CeleryExecutor and RabbitMQ
- Pull polling DAG for type-B carriers (Source F4 - Every 30 min with TaskFlow API and retries)
- Type-C file ingestion DAG (Source F5 - Batch processing every 4 h with defect sanitization)
- Distributed task execution and horizontal worker scaling (Operational Runbook)
- Container optimization and benchmark report

---

## 1. Service Architecture

The stack is orchestrated using `docker-compose.airflow.yml` and runs on the `cargaexpress` bridge network:

```
+-----------------------------------------------------------------------------------+
| Docker Network: control_tower_cargaexpress                                        |
|                                                                                   |
|  +--------------------+         AMQP 5672        +-----------------------------+  |
|  |  airflow-scheduler | -----------------------> |    rabbitmq                 |  |
|  +--------------------+                          | (3-management-alpine)       |  |
|            |                                     | Web UI: 15672               |  |
|            | (Task definitions)                  +-----------------------------+  |
|            v                                                    |                 |
|  +--------------------+                                         v (Queue tasks)   |
|  | airflow-webserver  |                          +-----------------------------+  |
|  | Web UI: 8080       |                          |    airflow-worker           |  |
|  +--------------------+                          |   (Celery Worker xN)        |  |
|            |                                     +-----------------------------+  |
|            |                                                    |                 |
|            +-----------------------+----------------------------+                 |
|                                    |                                              |
|                                    v                                              |
|                      +---------------------------+                                |
|                      |        airflow-db         |                                |
|                      |  (PostgreSQL 16 Metastore)|                                |
|                      |   Host port: 5433         |                                |
|                      +---------------------------+                                |
+-----------------------------------------------------------------------------------+
```

### Components:
1. **RabbitMQ (`rabbitmq:3-management-alpine`)**: Message Broker for Celery. Exposes AMQP port `5672` for worker message queues and port `15672` for the web management console.
2. **Airflow DB (`airflow-db`)**: Dedicated PostgreSQL 16 database for the Airflow metastore, isolated from the operational WMS database. Exposed on host: `5433`.
3. **Airflow Init (`airflow-init`)**: Ephemeral container running database migrations (`airflow db migrate`) and provisioning the initial administrator credentials.
4. **Airflow Webserver (`airflow-webserver`)**: Web UI administrative console running on port `8080`.
5. **Airflow Scheduler (`airflow-scheduler`)**: Monitors DAG lifecycles and dispatches scheduled tasks using `CeleryExecutor`.
6. **Airflow Worker (`airflow-worker`)**: Celery Worker processes consuming concurrent tasks queued in RabbitMQ. Supports horizontal scaling without container name collisions.
7. **Mounted Volumes**:
   - `./dags`: DAG files mounted to `/opt/airflow/dags`.
   - `./logs`: Execution logs mounted to `/opt/airflow/logs`.
   - `./plugins`: Custom plugins mounted to `/opt/airflow/plugins`.
   - `./data`: Ingestion batches mounted to `/opt/airflow/data`.

---

## 2. Design Conventions: TaskFlow API and Modularization

Aligned with project coding standards (TaskFlow API in English and strict separation of concerns):

1. **TaskFlow API Paradigm (@dag and @task)**:
   - Deprecates legacy `PythonOperator` in favor of `@dag` and `@task` decorators.
   - Values flow naturally as parameters and returns between tasks without manual XCom management.
2. **Modularization and Reusability**:
   - DAGs do not contain raw SQL statements or coupled business logic.
   - The orchestration layer communicates with backend ingestion services via the modular client `dags/utils/control_tower_client.py` (`ControlTowerClient`), reusing Sprint 2 Type B (`POST /api/v1/sync/type-b`) and Type C (`POST /api/v1/sync/type-c/upload`) connectors.
3. **100% English Nomenclature**:
   - Docstrings, task names, variables, logs, and exceptions are strictly standardized in English.

---

## 3. Deployment Instructions

### Step 1: Configure Environment Variables (Optional)
To customize credentials or ports, copy `.env.example` to `.env` or set:
```bash
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=admin
_AIRFLOW_WWW_USER_PASSWORD=admin
CONTROL_TOWER_API_URL=http://backend:8000
AIRFLOW_WORKER_REPLICAS=2
```

### Step 2: Initialize Airflow Metastore
```bash
docker compose -f docker-compose.airflow.yml up airflow-init
```

### Step 3: Start Airflow and RabbitMQ Services
```bash
docker compose -f docker-compose.airflow.yml up -d
```
*By default, 2 Celery worker instances start up (`control_tower-airflow-worker-1` and `control_tower-airflow-worker-2`).*

Verify container health:
```bash
docker compose -f docker-compose.airflow.yml ps
```

---

## 4. Implemented Ingestion and Validation DAGs

### A. Type A Simulator Polling Pipeline (`type_a_pull_polling`)
Orchestrates periodic batch pull sync against the Type A Webhook Simulator Receiver API (Source F3 extractor hook):
- **Schedule**: `*/30 * * * *` (every 30 minutes).
- **Resilience**: 3 retries with exponential backoff (`retry_exponential_backoff=True`) and a 20-minute ceiling.
- **Workflow**:
  1. `verify_backend_readiness`: Verifies backend API readiness.
  2. `poll_type_a_carriers`: Triggers `POST /api/v1/sync/type-a` to query simulator events, map raw statuses to canonical states, and update WMS.
  3. `evaluate_polling_metrics`: Aggregates normalized events, records anomalies, and logs warning alerts on errors.

### B. Type B Pull Polling Pipeline (`type_b_pull_polling`)
Executes scheduled REST polling against the 4 Type B carriers:
- **Schedule**: `*/30 * * * *` (every 30 minutes).
- **Resilience**: 3 retries with exponential backoff (`retry_exponential_backoff=True`) and a 20-minute ceiling to absorb carrier rate limits.
- **Workflow**:
  1. `verify_backend_readiness`: Verifies backend API readiness.
  2. `poll_type_b_carriers`: Triggers `POST /api/v1/sync/type-b` to query REST APIs, map raw statuses to canonical states, and update WMS.
  3. `evaluate_polling_metrics`: Aggregates normalized events, records anomalies, and logs warning alerts on errors.

### C. Type C Batch File Ingestion Pipeline (`type_c_file_ingestion`)
Processes periodic batch files (CSV/XLSX) in `data/type_C_simulation_data/`:
- **Schedule**: `0 */4 * * *` (every 4 hours).
- **Workflow**:
  1. `scan_incoming_files`: Detects incoming `.csv` and `.xlsx` staging files.
  2. `ingest_batch_files`: Resolves carrier name and uploads file to `POST /api/v1/sync/type-c/upload`, dropping repeated headers, stripping summary rows, checking SHA-256 idempotency, and normalizing events.
  3. `archive_processed_files`: Moves completed files to the `processed/` subfolder with timestamp prefixes.

### D. Distributed Validation Pipeline (`dag_distributed_validation`)
Audits task distribution across Celery workers and RabbitMQ:
- **Workflow**:
  1. `init_distributed_test`: Captures dispatcher metadata and timestamp.
  2. `worker_probe_partition_[1..4]`: 4 concurrent fan-out tasks recording hostname, PID, IP, and execution timestamps on Celery workers.
  3. `aggregate_distributed_evidence`: Fan-in task consolidating XCom metrics and emitting an operational distribution verdict.

---

## 5. Horizontal Worker Scaling

### 5.1 Scalability Mechanism
In `docker-compose.airflow.yml`, `airflow-worker` omits a static `container_name`, enabling native Docker Compose horizontal scaling.

#### Scale Workers at Runtime:
```bash
# Scale to 3 concurrent workers
docker compose -f docker-compose.airflow.yml up -d --scale airflow-worker=3

# Scale down to 2 workers
docker compose -f docker-compose.airflow.yml up -d --scale airflow-worker=2
```

---

## 6. Operational Runbook & Troubleshooting (Deliverable E-12)

### 6.1 Audit Distributed Execution
```bash
# Trigger distributed validation DAG
docker compose -f docker-compose.airflow.yml exec airflow-webserver airflow dags trigger dag_distributed_validation

# View fan-in aggregator logs
docker compose -f docker-compose.airflow.yml exec airflow-webserver airflow tasks logs dag_distributed_validation aggregate_distributed_evidence
```

### 6.2 Inspect Celery and RabbitMQ Status
```bash
# Ping active Celery workers
docker compose -f docker-compose.airflow.yml exec airflow-scheduler celery --app airflow.providers.celery.executors.celery_executor.app inspect ping

# Inspect active tasks per worker
docker compose -f docker-compose.airflow.yml exec airflow-scheduler celery --app airflow.providers.celery.executors.celery_executor.app inspect active

# List RabbitMQ queues, message counts, and consumers
docker compose -f docker-compose.airflow.yml exec rabbitmq rabbitmqctl list_queues name messages consumers
```

Web UI Verification:
1. Open [http://localhost:15672](http://localhost:15672) (credentials: `guest` / `guest`).
2. Navigate to **Queues**: Celery `default` queue must display consumers matching active worker replicas.

---

## 7. Automated Verification

### Run DAG Integrity Tests with Pytest
```bash
cd backend
uv run pytest tests/test_dags.py -v
```

### Compile DAGs Syntax
```bash
python -m py_compile dags/dag_type_a_polling.py
python -m py_compile dags/dag_type_b_polling.py
python -m py_compile dags/dag_type_c_ingestion.py
python -m py_compile dags/dag_distributed_validation.py
```

### Stop the Airflow Stack
```bash
docker compose -f docker-compose.airflow.yml down
```
*(Append `-v` to prune persistent volumes).*

---

## 8. Container Optimization & Benchmark Report

All Docker workloads across the CargaExpress platform have been refactored to hardened multi-stage builds.

### 8.1 Airflow Optimization Strategy
1. **Lightweight Base Images**:
   - `airflow-db`: `postgres:16-alpine` (117 MB vs. 634 MB Debian bookworm).
   - `rabbitmq`: `rabbitmq:3-management-alpine` (87.7 MB vs. > 250 MB standard).
2. **Eliminated Cold-Start Overhead (`Dockerfile.airflow`)**:
   - Provides pre-baked dependencies on user `airflow` (UID 50000) for deterministic deployment without runtime pip install delays.
3. **Resource & Polling Tuning**:
   - `AIRFLOW__CORE__LOAD_EXAMPLES: 'false'`: Eliminates 50+ demo DAGs.
   - `AIRFLOW__WEBSERVER__WORKERS: 2`: Bounds webserver memory usage.
   - `AIRFLOW__SCHEDULER__MIN_FILE_PROCESS_INTERVAL: 10`: Mitigates scheduler CPU consumption.

### 8.2 Consolidated Benchmark Summary

| Component / Subsystem | Base / Single-Stage | Multi-Stage Optimized | Compressed Transfer Size | Footprint Reduction | Runtime User | Key Optimizations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Backend (Control Tower API)** | python:3.12 (488 MB) | python:3.12-slim | **299 MB** | 69.6 MB | **-38.7%** | `appuser` (1000) | Stripped uv & gcc; bytecode compiled; /api/v1/ready healthcheck. |
| **Airflow Orchestrator (Custom)** | Standard setup (~2.3 GB) | apache/airflow:2.9.3 pre-baked | **2.01 GB** | 407 MB | **-290 MB** | `airflow` (50000) | Alpine PostgreSQL & RabbitMQ; demo DAGs disabled; worker tuning. |
| **Simulator A (Push Webhooks)** | python:3.12 (390 MB) | python:3.12-slim 3-stage | **205 MB** | 49.5 MB | **-47.4%** | `app` (10001) | Dedicated SQLite storage volume; isolated test stage. |
| **Simulator B - Carrier A (PostgreSQL)** | python:3.12-slim (485 MB) | python:3.12-slim multi-stage | **305 MB** | 71.0 MB | **-37.1%** | `appuser` (1000) | Compiled virtualenv; stripped build tools; automatic migrations. |
| **Simulator B - Carrier B (MySQL)** | python:3.12-slim (460 MB) | python:3.12-slim multi-stage | **278 MB** | 65.2 MB | **-39.5%** | `appuser` (1000) | Native PyMySQL driver; pre-compiled wheels. |
| **Simulator B - Carrier C (MongoDB)** | python:3.12-slim (435 MB) | python:3.12-slim multi-stage | **249 MB** | 58.8 MB | **-42.7%** | `appuser` (1000) | Lean pymongo runtime; zero relational database overhead. |
| **Simulator B - Carrier D (SQLite)** | python:3.12-slim (455 MB) | python:3.12-slim multi-stage | **277 MB** | 65.1 MB | **-39.1%** | `appuser` (1000) | Pre-configured /data directory with UID 1000 ownership. |
| **Simulator B - Tools (Seed / Generator)** | python:3.12-slim (425 MB) | python:3.12-slim multi-stage | **258 MB** | 60.4 MB | **-39.3%** | `appuser` (1000) | Batch seed and background generator running as unprivileged user. |
| **Simulator C (Batch Files & WMS Seed)** | python:3.12-slim (430 MB) | python:3.12-slim multi-stage | **257 MB** | 60.7 MB | **-40.2%** | `seeduser` (1000) | Frozen lockfile; uv binary stripped from final image. |

### 8.3 Key Takeaways & Operational Benefits
- **Over 1.1 GB Disk Space Saved**: Across all container images in the platform.
- **Runtime Security Compliance**: 100% of application and simulation containers run under non-root users (UID 1000, 10001, 50000).
- **Fast CI/CD Deployments**: Multi-stage layering and pre-compiled bytecode provide reusable image cache and faster cloud pulls.

---

## 9. Remote Logging to Amazon S3 & CloudWatch Logs Architecture

### 9.1 Overview & Operational Workflow
To guarantee log persistence, avoid local container disk saturation, and enable seamless cross-worker log inspection without disrupting developers or operators:
1. **Airflow Task Execution**: Celery workers stream logs locally while tasks run, and upon task completion, the native `S3TaskHandler` automatically uploads the full task log to the S3 bucket (`s3://${GOLD_S3_BUCKET}/airflow/logs/<dag_id>/<task_id>/<execution_date>/<try_number>.log`).
2. **Transparent Query Experience**: When an operator navigates to the Airflow Webserver UI (`http://localhost:8080`), clicks any task instance, and opens the **Log** tab, the webserver retrieves and streams the log file directly from S3. The interface and user experience remain identical to local execution.
3. **Local & Historical Fallback**: The host directory `./logs` remains mounted to `/opt/airflow/logs`. If S3 connectivity is unavailable or remote logging is explicitly disabled (`AIRFLOW__LOGGING__REMOTE_LOGGING=false`), Airflow automatically falls back to local disk logging.

### 9.2 Minimum IAM Policy (Least-Privilege Principle)
Apply the following least-privilege policy to the Airflow execution IAM role or user:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AirflowS3RemoteLoggingStorage",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::cargaexpress-datalake-staging-326204936524/airflow/logs/*"
    },
    {
      "Sid": "AirflowS3BucketListing",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::cargaexpress-datalake-staging-326204936524",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "airflow/logs/*"
          ]
        }
      }
    }
  ]
}
```

### 9.3 Cost Analysis & Financial Impact
In strict accordance with project financial governance, reusing existing AWS infrastructure yields negligible overhead:
- **S3 Storage (Standard)**: ~$0.023 per GB/month. Assuming 500 MB of monthly compressed execution logs: **<$0.02 USD / month**.
- **S3 API Requests (PUT/GET)**: $0.005 per 1,000 PUT requests, $0.0004 per 1,000 GET requests. For 20,000 task executions/month: **~$0.10 USD / month**.
- **No Paid Data Pipelines**: Amazon Data Firehose or paid third-party ingestion aggregators are omitted to avoid recurring hourly standing charges.
- **Estimated Total S3 Remote Logging Cost**: **< $0.15 USD / month**.

### 9.4 Log Inspection Runbook

#### Local Environment
* **Airflow Web UI**: Open `http://localhost:8080`, click on DAG -> Run -> Task -> **Log**.
* **Airflow Containers via Docker CLI**:
  ```bash
  docker compose -f docker-compose.airflow.yml logs -f --tail=100 airflow-scheduler
  docker compose -f docker-compose.airflow.yml logs -f --tail=100 airflow-worker
  docker compose -f docker-compose.airflow.yml logs -f --tail=100 airflow-webserver
  ```
* **FastAPI Backend**:
  ```bash
  docker compose logs -f --tail=100 backend
  ```

#### AWS Production Environment
* **FastAPI Real-Time Live Stream (CloudWatch Logs)**:
  ```bash
  aws logs tail /cargaexpress/backend --follow --region us-east-2
  ```
* **FastAPI Filter Errors (CloudWatch Logs)**:
  ```bash
  aws logs filter-log-events --log-group-name /cargaexpress/backend --filter-pattern "ERROR" --region us-east-2
  ```
* **Historical Airflow Logs on S3 (AWS CLI)**:
  ```bash
  aws s3 ls s3://cargaexpress-datalake-staging-326204936524/airflow/logs/ --recursive
  ```
* **Download Specific Task Log from S3**:
  ```bash
  aws s3 cp s3://cargaexpress-datalake-staging-326204936524/airflow/logs/type_b_pull_polling/poll_type_b_carriers/ ./task_run.log
  ```

