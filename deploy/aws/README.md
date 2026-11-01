# Kit de Despliegue Cloud en AWS · CargaExpress Control Tower (HU-39)

Guía declarativa y manual operativo para el despliegue de la infraestructura de producción de **CargaExpress Supply Chain Control Tower** sobre Amazon Web Services (AWS).

---

## 1. Arquitectura de Despliegue en AWS

```
                           Internet
                              │
                      [Route 53 / DNS]
                              │
              [Application Load Balancer (ALB)]
                              │
              ┌───────────────┴───────────────┐
              │  VPC (Subredes Privadas)      │
              ▼                               ▼
    [ECS Fargate: Backend]          [ECS Fargate: Airflow]
     Port 8000 (/api/v1/health)      Port 8080 (Webserver)
              │                               │
              ├───────────────┬───────────────┤
              ▼               ▼               ▼
      [Amazon RDS PG]   [Amazon MQ]     [CloudWatch]
        PostgreSQL 16     RabbitMQ       Log Groups
              ▲
              │
    [ECS Fargate: Worker]
       (Consumer Worker)
```

### Componentes de Cómputo y Dimensionamiento

| Servicio | Tipo de Cómputo | vCPU / RAM | Modo de Red | Puerto | Health Check |
|---|---|---|---|---|---|
| **Backend API** | ECS Fargate | 0.25 vCPU (256) / 0.5 GB (512) | `awsvpc` | 8000 | `GET /api/v1/health` |
| **Consumer Worker** | ECS Fargate | 0.25 vCPU (256) / 0.5 GB (512) | `awsvpc` | N/A | Signal/Loop Heartbeat |
| **Airflow Orchestrator** | ECS Fargate | 1.0 vCPU (1024) / 2.0 GB (2048) | `awsvpc` | 8080 / 8974 | `GET :8080/health` / `:8974/health` |

---

## 2. Contenido del Directorio `deploy/aws/`

- [`task-definition-backend.json`](task-definition-backend.json): Definición Fargate para el API FastAPI con logs en CloudWatch (`/ecs/cargaexpress-backend`) y health check nativo.
- [`task-definition-worker.json`](task-definition-worker.json): Definición Fargate para el worker consumidor RabbitMQ con comando `python -m app.worker`.
- [`task-definition-airflow.json`](task-definition-airflow.json): Definición Fargate multi-contenedor para Apache Airflow (`airflow-webserver` y `airflow-scheduler`).
- [`alb-target-group.json`](alb-target-group.json): Especificación del Target Group con IP target type y matcher HTTP 200 en `/api/v1/health`.
- [`service-backend.json`](service-backend.json): Especificación del servicio ECS Fargate para el backend conectado al ALB con circuit breaker activado.
- [`service-worker.json`](service-worker.json): Especificación del servicio ECS Fargate para el worker desacoplado.

---

## 3. Preparación de Secretos en AWS Secrets Manager

Antes de desplegar los servicios en ECS, crear los siguientes secretos en **AWS Secrets Manager** (región `us-east-1`):

```bash
# 1. Database URL para RDS PostgreSQL
aws secretsmanager create-secret \
  --name "cargaexpress/production/database-url" \
  --description "Connection string for CargaExpress RDS PostgreSQL database" \
  --secret-string "postgresql+asyncpg://cargaexpress_app:<STRONG_PASSWORD_32_CHARS>@<RDS_ENDPOINT>:5432/cargaexpress?ssl=require"

# 2. RabbitMQ Broker URL
aws secretsmanager create-secret \
  --name "cargaexpress/production/rabbitmq-url" \
  --description "AMQPS Connection string for RabbitMQ broker" \
  --secret-string "amqps://cargaexpress_broker:<RABBITMQ_PASSWORD>@<BROKER_ENDPOINT>:5671/"

# 3. API Key de Consumidores (mínimo 32 caracteres)
aws secretsmanager create-secret \
  --name "cargaexpress/production/api-key" \
  --description "General API Key for consumer systems" \
  --secret-string "$(openssl rand -hex 32)"

# 4. Admin API Key (mínimo 32 caracteres)
aws secretsmanager create-secret \
  --name "cargaexpress/production/admin-api-key" \
  --description "Admin API Key for protected endpoints (ADR-0005)" \
  --secret-string "$(openssl rand -hex 32)"

# 5. Brand API Keys (JSON mapping de tokens >= 32 chars)
aws secretsmanager create-secret \
  --name "cargaexpress/production/brand-api-keys" \
  --description "Per-brand API authentication dictionary" \
  --secret-string '{"'$(openssl rand -hex 32)'": 1, "'$(openssl rand -hex 32)'": 2}'

# 6. Airflow Fernet Key
aws secretsmanager create-secret \
  --name "cargaexpress/production/airflow-fernet-key" \
  --description "Fernet encryption key for Airflow" \
  --secret-string "$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

---

## 4. Roles IAM Requeridos

### Execution Role (`cargaexpress-ecs-execution-role`)
Permite a Fargate descargar imágenes de ECR, escribir logs a CloudWatch y resolver secretos:
- Política administrada: `arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy`
- Política inline de lectura de secretos:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "ssm:GetParameters"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:<AWS_ACCOUNT_ID>:secret:cargaexpress/production/*",
        "arn:aws:ssm:us-east-1:<AWS_ACCOUNT_ID>:parameter/cargaexpress/production/*"
      ]
    }
  ]
}
```

---

## 5. Procedimiento de Despliegue Manual Paso a Paso

### Paso 1: Migración de Base de Datos RDS
```bash
./scripts/migrate_rds.sh \
  -H "<RDS_ENDPOINT>" \
  -U "cargaexpress_app" \
  -P "<DB_PASSWORD>" \
  -d "cargaexpress"
```

### Paso 2: Registrar Task Definitions en ECS
```bash
# Reemplazar <AWS_ACCOUNT_ID> con el ID de la cuenta AWS
sed "s/<AWS_ACCOUNT_ID>/${AWS_ACCOUNT_ID}/g" deploy/aws/task-definition-backend.json > /tmp/task-backend.json
aws ecs register-task-definition --cli-input-json file:///tmp/task-backend.json

sed "s/<AWS_ACCOUNT_ID>/${AWS_ACCOUNT_ID}/g" deploy/aws/task-definition-worker.json > /tmp/task-worker.json
aws ecs register-task-definition --cli-input-json file:///tmp/task-worker.json
```

### Paso 3: Actualizar Servicios ECS
```bash
aws ecs update-service \
  --cluster cargaexpress-production \
  --service cargaexpress-backend-service \
  --task-definition cargaexpress-backend \
  --force-new-deployment

aws ecs update-service \
  --cluster cargaexpress-production \
  --service cargaexpress-worker-service \
  --task-definition cargaexpress-worker \
  --force-new-deployment
```

### Paso 4: Monitoreo y Rollback
Los servicios cuentan con `deploymentCircuitBreaker` (`enable=true`, `rollback=true`). En caso de fallas consecutivas en las comprobaciones de salud del contenedor (`/api/v1/health`), ECS revierte automáticamente la tarea a la versión estable anterior sin intervención manual.
