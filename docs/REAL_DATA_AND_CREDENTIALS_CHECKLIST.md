# CargaExpress Supply Chain Control Tower
# Real Data and Credentials Inventory & Configuration Checklist

**Document Version:** 1.0.0  
**Target Environment:** Staging (`us-east-2` Ohio)  
**Security Classification:** Confidential  
**Deployment Policy:** Authorization strictly restricted to **RDS ONLY** until this checklist is fulfilled and verified.

---

## 1. Executive Summary

This inventory documents **every real credential, API key, external endpoint, and operational dataset** required for the production-grade deployment and end-to-end operation of the CargaExpress Supply Chain Control Tower.

In accordance with strict security standards:
- **No real passwords, private keys, or tokens must ever be committed to Git or pasted into chat.**
- All application secrets must be stored directly in **AWS Secrets Manager** or **GitHub Repository Secrets**.
- Values not yet provided by the business or infrastructure owners are marked explicitly as `TBD`.

---

## 2. Master User Input Checklist

| # | Variable / Credential / Resource Name | Type | Mandatory? | Where to Enter | Current Value / Status | Description & Purpose |
|---|---|---|---|---|---|---|
| **1** | `alert_email` | Operational Data | **Mandatory** | `terraform.tfvars` or `TF_VAR_alert_email` | `TBD` (was `.local`) | Real, monitored DevOps email address to receive CloudWatch Alarms and SNS notifications (ALB 5xx, RDS CPU, Budget overruns). |
| **2** | `ADMIN_API_KEY` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | High-entropy key ($\ge 32$ chars) protecting administrative endpoints (`/api/v1/admin/*`, state mapping reloads). |
| **3** | `API_KEY` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | Internal service-to-service key ($\ge 32$ chars) used by Control Tower microservices and health probes. |
| **4** | `BRAND_API_KEYS` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | JSON mapping of client brand API keys to their database tenant IDs: `{"<key_32_chars>": <brand_id>}`. |
| **5** | `CARRIER_API_KEYS` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | JSON mapping of carrier API keys to their database carrier IDs: `{"<key_32_chars>": <carrier_id>}`. |
| **6** | `WEBHOOK_SECRET` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | Shared secret ($\ge 32$ chars) used for HMAC-SHA256 signature verification on incoming carrier webhook payloads. |
| **7** | `CARRIER_WEBHOOK_TOKENS` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | JSON dictionary mapping carrier slugs to expected Bearer tokens for the 5 Type A carrier integrations. |
| **8** | `TYPE_A_SIMULATOR_URL` / Webhook Endpoints | Operational Data | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `https://cargaexpress-simulator-b.mooo.com/sim-a` (or real carrier URLs) | Base URL for Type A carrier event simulator or real webhook dispatch endpoints. |
| **9** | `TYPE_B_CARRIERS_URLS` | Operational Data | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | JSON dictionary with HTTPS endpoints for the 4 Type B REST API carriers polled every 30 minutes. |
| **10** | `TYPE_C_CARRIERS_URLS` | Operational Data | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | `TBD` | JSON dictionary with endpoints or download URLs for the 3 Type C batch flat-file carriers. |
| **11** | `MINIO_ENDPOINT` & MinIO Credentials | Credential | **Optional / Staging** | AWS Secrets Manager (`cargaexpress/staging/app_secrets`) | Pre-configured to simulator / S3 fallback | Endpoint, Access Key, Secret Key and Bucket for external flat-file batch downloads. |
| **12** | `AIRFLOW__CORE__FERNET_KEY` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/airflow`) | Pre-seeded (Needs rotation) | 32-byte base64-encoded key used by Airflow to encrypt database connections and sensitive DAG variables. |
| **13** | `AIRFLOW__WEBSERVER__SECRET_KEY` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/airflow`) | `TBD` | Flask session secret key ($\ge 32$ chars) for signing Airflow Web UI cookies. |
| **14** | `RABBITMQ_PASSWORD` | Credential | **Mandatory** | AWS Secrets Manager (`cargaexpress/staging/rabbitmq`) | Auto-generated in Terraform | Password for the RabbitMQ administrative user `cargaexpress`. |
| **15** | `POSTGRES_PASSWORD` | Credential | **Active (RDS)** | AWS Secrets Manager (`cargaexpress/staging/database`) | Configured in RDS instance | Master administrator password for RDS PostgreSQL 16. |
| **16** | Initial WMS Orders Dataset | Operational Data | **Mandatory** | Amazon S3 Landing Bucket | `TBD` | Historical or staging CSV/Parquet files containing orders, dispatches, and initial shipping label records. |
| **17** | Carrier State Mappings Seed | Operational Data | **Mandatory** | Database table `carrier_state_mappings` | Pre-seeded in migrations | Canonical mapping rules translating carrier raw statuses to unified states (`CREATED`, `IN_TRANSIT`, `DELIVERED`, etc.). |
| **18** | Penalty & SLA Schedule Seed | Operational Data | **Mandatory** | Database table `universal_penalty_configs` | Pre-seeded in migrations | Delay day thresholds, penalty percentages, and maximum financial penalty caps per carrier contract. |
| **19** | Nager.Date Public Holiday API | Operational Data | **Mandatory** | Public API (`https://date.nager.at/api/v3`) | Available | External calendar service for Colombia (CO), Mexico (MX), and Peru (PE) to compute business-day SLAs. |
| **20** | `acm_certificate_arn` | Credential / Infrastructure | **Optional for Staging** | `terraform.tfvars` / AWS ACM | `null` (HTTP 80 fallback) | AWS Certificate Manager ARN for ALB HTTPS listener (required for production TLS termination). |

---

## 3. Step-by-Step Instructions: Where and How to Enter Information

### A. AWS Secrets Manager (Application & Orchestration Secrets)
Do not pass credentials through chat or text files. Navigate to AWS Secrets Manager to populate the four secret containers:

1. **Sign in to AWS Management Console** and select Region **`us-east-2` (Ohio)**.
2. Navigate to **AWS Secrets Manager** -> **Secrets**.
3. Select the secret to edit:
   - `cargaexpress/staging/app_secrets`
   - `cargaexpress/staging/database`
   - `cargaexpress/staging/rabbitmq`
   - `cargaexpress/staging/airflow`
4. Click **Retrieve secret value** -> **Edit**.
5. Switch to **Plaintext** or use the **Key/value** tab:
   - For `cargaexpress/staging/app_secrets`, replace the placeholder values (`CHANGE_ME_*`) for `ADMIN_API_KEY`, `API_KEY`, `WEBHOOK_SECRET`, `BRAND_API_KEYS`, and `CARRIER_API_KEYS` with your real keys.
   - For `cargaexpress/staging/airflow`, replace `CHANGE_ME_AIRFLOW_SECRET_KEY` with a secure random 32-character string.
6. Click **Save**.

---

### B. Terraform Staging Variables (`terraform.tfvars` or Environment Variables)
For infrastructure operational data that does not contain sensitive passwords:

1. Open `infrastructure/terraform/environments/staging/terraform.tfvars`.
2. Update the `alert_email` parameter with your real operational email address:
   ```hcl
   alert_email = "real-devops-email@yourdomain.com"
   ```
3. Alternatively, export it in your environment without modifying files:
   ```powershell
   $env:TF_VAR_alert_email = "real-devops-email@yourdomain.com"
   ```

---

### C. Amazon S3 Data Lake (Operational Flat Files & WMS Data)
To provide real operational data files for batch pipelines and analytics:

1. Navigate to **Amazon S3** -> **Buckets** in AWS Console (`us-east-2`).
2. Select the Data Lake bucket: `cargaexpress-staging-datalake-326204936524`.
3. Upload files to their respective layer folders:
   - **WMS Historical Orders & Dispatches**:
     `s3://cargaexpress-staging-datalake-326204936524/landing/wms/`
   - **Type C Carrier Batch Files (CSV / Excel / XML)**:
     `s3://cargaexpress-staging-datalake-326204936524/landing/type-c/<carrier_slug>/`
   - **Carrier Contracts & Rate Cards**:
     `s3://cargaexpress-staging-datalake-326204936524/landing/contracts/`

---

### D. GitHub Actions Repository Secrets (CI/CD Pipeline)
When enabling automated deployment workflows via GitHub Actions:

1. Navigate to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Under **Repository secrets**, ensure the following are configured:
   - `AWS_ROLE_TO_ASSUME`: ARN of the IAM OIDC role (`arn:aws:iam::326204936524:role/cargaexpress-staging-github-actions-role`).
   - `AWS_REGION`: `us-east-2`.
   - `ALERT_EMAIL`: Real email for operational alerts.

---

## 4. Operational Carrier & Integration Specifications

### 1. Five Type A Carriers (Push Webhooks)
- **Integration Pattern**: Real-time push webhooks sent by carriers to `/api/v1/webhooks/{carrier_slug}`.
- **Security**: HMAC-SHA256 signature in `X-Hub-Signature-256` header using `WEBHOOK_SECRET`, or Bearer token in `Authorization` header matching `CARRIER_WEBHOOK_TOKENS`.
- **Requirements**:
  - Valid carrier slugs (e.g., `servientrega`, `coordinadora`, `tcc`, `deprisa`, `envia`).
  - Pre-seeded state mapping records in table `carrier_state_mappings` for each carrier.

### 2. Four Type B Carriers (REST API Polling)
- **Integration Pattern**: Scheduled HTTP GET polling executed every 30 minutes via Airflow DAG `dag_type_b_polling`.
- **Required Data**:
  - Base URL, authentication credentials (API key, Basic Auth, or OAuth2), and query parameters for tracking updates.
  - Endpoints configured in `TYPE_B_CARRIERS_URLS`.

### 3. Three Type C Carriers (Batch Flat Files)
- **Integration Pattern**: Batch file pickup (CSV, Excel `.xlsx`, XML) executed every 4 hours via Airflow DAG `dag_type_c_ingestion`.
- **Required Data**:
  - Ingestion bucket location (`landing/type-c/`) or SFTP/MinIO credentials.
  - Column mapping definitions (handling heterogeneous headers such as `guia`, `tracking_number`, `awb`).

### 4. SLA & Financial Engine Configuration
- **SLA Rule RN-03**:
  - Daily cutoff: 16:00 local time. Orders dispatched after 16:00 start SLA on the next business day.
  - Calendar exclusions: Sundays and destination country public holidays fetched via Nager.Date API (CO, MX, PE) and cached in `calendar_holidays`.
- **Financial Penalties**:
  - Universal Progressive Penalty Scale (`NO_DELAY`, `LOW`, `MODERATE`, `HIGH`, `CRITICAL`) configured in table `universal_penalty_configs`.

---

## 5. Deployment Policy & Scope Confirmation

- **Current Authorized Scope**: **Amazon RDS PostgreSQL ONLY**.
- **Pending Infrastructure (111 resources)**: VPC networking, NAT Gateway, ALB, S3 Data Lake, RabbitMQ EC2, ECS Fargate, Airflow, Athena, and CloudWatch Alarms are fully planned in `tfplan` but **will NOT be applied** without explicit, written confirmation.
- **Readiness Criteria**: Staging deployment will not be declared complete until:
  1. Real `alert_email` is provided.
  2. The 4 Secrets Manager containers are populated with real secrets.
  3. User issues explicit authorization to apply the remaining infrastructure.
