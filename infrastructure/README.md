# CargaExpress Control Tower – AWS Infrastructure as Code (Terraform)

This directory contains the production-ready Terraform Infrastructure as Code (IaC) configuration for the **CargaExpress Supply Chain Control Tower** on Amazon Web Services (AWS).

---

## 1. Architecture Overview & Component Mapping

The infrastructure translates the approved CargaExpress architectural design into modular, secure, and reproducible Terraform resources deployed in the `us-east-2` (Ohio) region.

```
                              INTERNET (Public)
                                      │
                              [ Internet Gateway ]
                                      │
   ┌──────────────────────────────────▼────────────────────────────────────────┐
   │ PUBLIC SUBNETS (10.0.1.0/24, 10.0.2.0/24)                                │
   │  - Application Load Balancer (ALB)                                        │
   │  - NAT Gateway (Elastic IP for controlled egress)                         │
   └──────────────────────────────────┬────────────────────────────────────────┘
                                      │
   ┌──────────────────────────────────▼────────────────────────────────────────┐
   │ PRIVATE APPLICATION SUBNETS (10.0.10.0/24, 10.0.11.0/24)                  │
   │  - ECS Fargate: Webhook Receiver (/api/v1/webhooks/*)                     │
   │  - ECS Fargate: Query APIs (/api/v1/sla/*, /api/v1/analytics/*)          │
   │  - ECS Fargate: Background Worker (Consumer)                             │
   │  - ECS Fargate: Airflow Webserver, Scheduler, Celery Workers              │
   │  - ECS Fargate: Spark ETL Batch Tasks (4 vCPU / 16 GB RAM)                │
   │  - EC2: RabbitMQ Broker (AMQP 5672, DLQ, Exchange)                       │
   └──────────────────────────────────┬────────────────────────────────────────┘
                                      │
   ┌──────────────────────────────────▼────────────────────────────────────────┐
   │ PRIVATE DATABASE SUBNETS (10.0.20.0/24, 10.0.21.0/24)                    │
   │  - Amazon RDS PostgreSQL 16 (gp3 KMS-encrypted, TLS enforced)            │
   │    Logical DBs: wms, opersolon (cargaexpress), liquidsolon, airflow       │
   └───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```text
infrastructure/terraform/
├── environments/
│   ├── production/                 # Production environment root configuration
│   │   ├── main.tf                 # Module orchestration
│   │   ├── variables.tf            # Configurable production variables
│   │   ├── outputs.tf              # Production resource endpoints and ARNs
│   │   ├── backend.tf              # S3 + DynamoDB remote state backend configuration
│   │   └── terraform.tfvars.example
│   └── staging/                    # Staging environment (cost-optimized)
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       ├── backend.tf
│       └── terraform.tfvars.example
└── modules/
    ├── networking/                 # VPC, 6 Subnets (Public/Private), IGW, NAT GW, SGs
    ├── security/                   # KMS CMK, Secrets Manager, ECS Task & Execution IAM roles
    ├── rds/                        # RDS PostgreSQL 16, DB subnet group, TLS parameter group
    ├── rabbitmq/                   # EC2 instance (t3.medium), EBS gp3 KMS, queues & DLQs
    ├── ecs/                        # ECS Cluster, Fargate services (Receiver, APIs, Worker), ALB
    ├── airflow/                    # Airflow Webserver, Scheduler, Celery Workers, Spark ETL
    ├── s3_datalake/                # S3 Data Lake (Landing, Bronze, Silver, Gold), Athena bucket
    ├── athena/                     # Glue Data Catalog (Gold star schema tables) & Athena workgroup
    ├── monitoring/                 # ECR container repositories, SNS topic, CloudWatch Alarms
    └── cicd/                       # GitHub Actions OIDC Identity Provider & IAM deploy role
```

---

## 3. Database Separation Strategy

The reference architecture specifies four distinct logical data areas:
1. `wms`: Upstream Warehouse Management System data and ingestion staging.
2. `opersolon`: Core operational Control Tower database (orders, tracking events, canonical states).
3. `liquidsolon`: Financial settlements, penalty clearinghouse, and netting balances.
4. `airflow`: Apache Airflow metastore (DAG runs, task instances, task logs).

In AWS RDS PostgreSQL, these areas are managed as distinct logical databases within the encrypted RDS instance:
- The default operational database is `cargaexpress` (aliased to `opersolon` for full backward compatibility).
- Airflow operates against the dedicated `airflow` database.
- Dedicated schemas or databases `wms` and `liquidsolon` are isolated via PostgreSQL role-level permissions.

---

## 4. Analytical Data Lake & Athena Model

- **S3 Bucket**: `cargaexpress-datalake-${environment}-${account_id}`
- **Prefixes**:
  - `landing/`: Incoming raw files (DataCo, carrier CSV/Excel, holiday definitions).
  - `bronze/`: Immutable raw data lake layer.
  - `silver/`: Cleaned, validated, and normalized Parquet files.
  - `gold/`: Kimball dimensional Star Schema in Parquet format, date-partitioned (`year=YYYY/month=MM/`).
- **PII Protection**: Gold layer schemas explicitly exclude personal customer data (names, identification numbers, raw contact information), maintaining only surrogate keys and business metrics.
- **Glue Data Catalog**: Database `cargaexpress_gold_${environment}` containing external Parquet tables for:
  - `fact_shipments_sla`
  - `fact_financial_penalties`
  - `dim_carriers`
  - `dim_brands`

---

## 5. Deployment Guide

### Prerequisites
- AWS CLI v2 configured with appropriate credentials.
- Terraform `>= 1.5.0` installed.
- S3 bucket and DynamoDB table created for remote state locking.

### Step 1: Initialize Working Directory
```bash
cd infrastructure/terraform/environments/production
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with account-specific values

terraform init
```

### Step 2: Validate Configuration
```bash
terraform validate
```

### Step 3: Review Execution Plan
```bash
terraform plan -out=tfplan
```

### Step 4: Apply (Only upon explicit authorization)
```bash
# WARNING: Requires project owner approval before running
terraform apply tfplan
```

### Step 5: Rollback Procedure
If a deployment needs to be cleanly rolled back:
```bash
# Revert to previous git commit or targeted destroy:
terraform plan -destroy -out=destroy.plan
terraform apply destroy.plan
```
