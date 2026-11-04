# Runbook de Despliegue en AWS: CargaExpress Control Tower

Este documento establece las instrucciones operativas paso a paso para aprovisionar, configurar y desplegar el backend y los componentes de soporte de CargaExpress Control Tower en Amazon Web Services (AWS). Todos los comandos presentados estan probados con AWS CLI v2 y disenados para ejecucion secuencial en la region `us-east-2` (Ohio).

---

## Parametros base de ejecucion

Antes de iniciar, exporta las siguientes variables de entorno en tu terminal bash o zsh para parametrizar los comandos:

```bash
export AWS_REGION="us-east-2"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
export ENVIRONMENT="production"
export PROJECT_NAME="cargaexpress"
export VPC_CIDR="10.0.0.0/16"
```

Verifica la identidad activa y permisos en AWS:

```bash
aws sts get-caller-identity
```

---

## Prerrequisitos de infraestructura de red y seguridad

La arquitectura requiere aislamiento de componentes en subredes publicas y privadas distribuidas en dos zonas de disponibilidad (`us-east-2a` y `us-east-2b`).

```
Internet
   |
[ Internet Gateway ]
   |
+-- Public Subnets (10.0.1.0/24, 10.0.2.0/24) ----------------+
|  [ Application Load Balancer ]      [ NAT Gateway ]         |
+--------------------------------------------|----------------+
                                             | (Egress outbound)
+-- Private Subnets App (10.0.10.0/24, 10.0.11.0/24) ---------+
|  [ ECS Fargate: Backend API ]      [ ECS Fargate: Worker ]  |
+-------------------------------------------------------------+
                                             | (Port 5432)
+-- Private Subnets DB (10.0.20.0/24, 10.0.21.0/24) ----------+
|  [ Amazon RDS PostgreSQL 16 ]                               |
+-------------------------------------------------------------+
```

### 1. Creacion de VPC y subredes

```bash
# 1. Crear VPC
VPC_ID=$(aws ec2 create-vpc \
  --cidr-block $VPC_CIDR \
  --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=${PROJECT_NAME}-vpc}]" \
  --query "Vpc.VpcId" --output text)

aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames "{\"Value\":true}"
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-support "{\"Value\":true}"

# 2. Crear Internet Gateway
IGW_ID=$(aws ec2 create-internet-gateway \
  --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=${PROJECT_NAME}-igw}]" \
  --query "InternetGateway.InternetGatewayId" --output text)
aws ec2 attach-internet-gateway --vpc-id $VPC_ID --internet-gateway-id $IGW_ID

# 3. Crear Subredes Publicas (ALB, NAT)
PUB_SUB_A=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 --availability-zone us-east-2a \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${PROJECT_NAME}-public-2a}]" \
  --query "Subnet.SubnetId" --output text)
PUB_SUB_B=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.2.0/24 --availability-zone us-east-2b \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${PROJECT_NAME}-public-2b}]" \
  --query "Subnet.SubnetId" --output text)

# 4. Crear Subredes Privadas para Aplicacion (ECS Fargate)
PRIV_SUB_APP_A=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.10.0/24 --availability-zone us-east-2a \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${PROJECT_NAME}-private-app-2a}]" \
  --query "Subnet.SubnetId" --output text)
PRIV_SUB_APP_B=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.11.0/24 --availability-zone us-east-2b \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${PROJECT_NAME}-private-app-2b}]" \
  --query "Subnet.SubnetId" --output text)

# 5. Crear Subredes Privadas para Base de Datos (RDS PostgreSQL)
PRIV_SUB_DB_A=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.20.0/24 --availability-zone us-east-2a \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${PROJECT_NAME}-private-db-2a}]" \
  --query "Subnet.SubnetId" --output text)
PRIV_SUB_DB_B=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.21.0/24 --availability-zone us-east-2b \
  --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${PROJECT_NAME}-private-db-2b}]" \
  --query "Subnet.SubnetId" --output text)
```

### 2. Tablas de ruteo y NAT Gateway

Las tareas Fargate en subredes privadas requieren salida a internet mediante NAT Gateway para descargar dependencias, consultar APIs externas de transportadoras y registrar logs y telemetria en AWS CloudWatch.

```bash
# 1. Asignar Elastic IP y crear NAT Gateway en subred publica A
EIP_ALLOC=$(aws ec2 allocate-address --domain vpc --query "AllocationId" --output text)
NAT_GW_ID=$(aws ec2 create-nat-gateway --subnet-id $PUB_SUB_A --allocation-id $EIP_ALLOC \
  --tag-specifications "ResourceType=natgateway,Tags=[{Key=Name,Value=${PROJECT_NAME}-nat}]" \
  --query "NatGateway.NatGatewayId" --output text)

echo "Esperando disponibilidad de NAT Gateway..."
aws ec2 wait nat-gateway-available --nat-gateway-ids $NAT_GW_ID

# 2. Configurar tabla de ruteo publica
PUB_RT=$(aws ec2 create-route-table --vpc-id $VPC_ID \
  --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=${PROJECT_NAME}-public-rt}]" \
  --query "RouteTable.RouteTableId" --output text)
aws ec2 create-route --route-table-id $PUB_RT --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID
aws ec2 associate-route-table --route-table-id $PUB_RT --subnet-id $PUB_SUB_A
aws ec2 associate-route-table --route-table-id $PUB_RT --subnet-id $PUB_SUB_B

# 3. Configurar tabla de ruteo privada
PRIV_RT=$(aws ec2 create-route-table --vpc-id $VPC_ID \
  --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=${PROJECT_NAME}-private-rt}]" \
  --query "RouteTable.RouteTableId" --output text)
aws ec2 create-route --route-table-id $PRIV_RT --destination-cidr-block 0.0.0.0/0 --nat-gateway-id $NAT_GW_ID
aws ec2 associate-route-table --route-table-id $PRIV_RT --subnet-id $PRIV_SUB_APP_A
aws ec2 associate-route-table --route-table-id $PRIV_RT --subnet-id $PRIV_SUB_APP_B
```

### 3. Grupos de seguridad (Security Groups)

Se configuran cuatro grupos de seguridad con principio de menor privilegio:

```bash
# Security Group para ALB
ALB_SG=$(aws ec2 create-security-group --group-name "${PROJECT_NAME}-alb-sg" \
  --description "Acceso publico HTTP y HTTPS hacia ALB" --vpc-id $VPC_ID --query "GroupId" --output text)
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0

# Security Group para Backend y Worker en ECS Fargate
ECS_SG=$(aws ec2 create-security-group --group-name "${PROJECT_NAME}-ecs-sg" \
  --description "Trafico interno desde ALB hacia contenedores FastAPI" --vpc-id $VPC_ID --query "GroupId" --output text)
aws ec2 authorize-security-group-ingress --group-id $ECS_SG --protocol tcp --port 8000 --source-group $ALB_SG

# Security Group para RDS PostgreSQL
RDS_SG=$(aws ec2 create-security-group --group-name "${PROJECT_NAME}-rds-sg" \
  --description "Acceso a base de datos PostgreSQL desde tareas ECS" --vpc-id $VPC_ID --query "GroupId" --output text)
aws ec2 authorize-security-group-ingress --group-id $RDS_SG --protocol tcp --port 5432 --source-group $ECS_SG

# Security Group para RabbitMQ
RABBITMQ_SG=$(aws ec2 create-security-group --group-name "${PROJECT_NAME}-rabbitmq-sg" \
  --description "Acceso a broker AMQP desde tareas ECS y workers" --vpc-id $VPC_ID --query "GroupId" --output text)
aws ec2 authorize-security-group-ingress --group-id $RABBITMQ_SG --protocol tcp --port 5672 --source-group $ECS_SG
```

---

## Paso 1: Creacion de repositorio en Amazon ECR, build y push

El backend utiliza una construccion multi-stage con Python 3.12 y el gestor de paquetes `uv`. La etapa final (`final`) genera una imagen de produccion sin herramientas de compilacion.

### 1. Crear el repositorio en ECR

```bash
aws ecr create-repository \
  --repository-name "${PROJECT_NAME}/backend" \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256 \
  --region $AWS_REGION
```

### 2. Autenticar Docker contra el registro ECR

```bash
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
```

### 3. Compilar la imagen y publicar en ECR

Ejecuta estos comandos desde la raiz del repositorio `control_tower`:

```bash
IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/backend"
COMMIT_TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "initial")

# Compilacion usando el target final de produccion
docker build \
  --target final \
  -t "${IMAGE_URI}:${COMMIT_TAG}" \
  -t "${IMAGE_URI}:latest" \
  -f backend/Dockerfile .

# Publicacion de las etiquetas en ECR
docker push "${IMAGE_URI}:${COMMIT_TAG}"
docker push "${IMAGE_URI}:latest"
```

### Opcion automatizada con script

El repositorio incluye el script `scripts/build_and_push_ecr.sh` (y `scripts/build_and_push_ecr.ps1` para PowerShell) para automatizar la creacion de repositorios, login en Docker, build multi-stage y publicacion:

```bash
# En Linux/macOS
chmod +x scripts/build_and_push_ecr.sh
./scripts/build_and_push_ecr.sh --region "$AWS_REGION" --account-id "$AWS_ACCOUNT_ID" --create-repos

# En Windows PowerShell
.\scripts\build_and_push_ecr.ps1 -Region $env:AWS_REGION -AccountId $env:AWS_ACCOUNT_ID -CreateRepos
```

---

## Paso 2: Aprovisionamiento de Amazon RDS PostgreSQL 16 y migraciones con Alembic

### 1. Crear Subnet Group de base de datos

RDS requiere un grupo de subredes que abarque al menos dos zonas de disponibilidad privadas:

```bash
aws rds create-db-subnet-group \
  --db-subnet-group-name "${PROJECT_NAME}-db-subnet-group" \
  --db-subnet-group-description "Subredes privadas de base de datos para CargaExpress" \
  --subnet-ids "$PRIV_SUB_DB_A" "$PRIV_SUB_DB_B"
```

### 2. Aprovisionar instancia RDS PostgreSQL 16

```bash
DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9')

aws rds create-db-instance \
  --db-instance-identifier "${PROJECT_NAME}-db" \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 16.3 \
  --master-username postgres \
  --master-user-password "$DB_PASSWORD" \
  --allocated-storage 20 \
  --max-allocated-storage 100 \
  --storage-type gp3 \
  --vpc-security-group-ids "$RDS_SG" \
  --db-subnet-group-name "${PROJECT_NAME}-db-subnet-group" \
  --db-name cargaexpress \
  --backup-retention-period 7 \
  --storage-encrypted \
  --no-publicly-accessible \
  --region $AWS_REGION

echo "Esperando que la instancia RDS complete su aprovisionamiento..."
aws rds wait db-instance-available --db-instance-identifier "${PROJECT_NAME}-db"

DB_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier "${PROJECT_NAME}-db" \
  --query "DBInstances[0].Endpoint.Address" --output text)

echo "RDS Endpoint: $DB_ENDPOINT"
```

### 3. Ejecucion de migraciones de base de datos con Alembic

La instancia RDS reside en subredes privadas no accesibles desde internet. Para aplicar las migraciones de esquema versionadas en produccion se utiliza una tarea puntual (one-off task) en ECS Fargate dentro de la VPC:

```bash
# Crear tarea de migracion en Fargate que ejecuta alembic upgrade head
aws ecs run-task \
  --cluster "${PROJECT_NAME}-cluster" \
  --task-definition "cargaexpress-backend" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIV_SUB_APP_A,$PRIV_SUB_APP_B],securityGroups=[$ECS_SG],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides": [{"name": "backend", "command": ["alembic", "upgrade", "head"]}]}' \
  --region $AWS_REGION
```

Alternativamente, si se cuenta con conexion segura mediante AWS Client VPN o Bastion Host en la subred publica:

```bash
export DATABASE_URL="postgresql+asyncpg://postgres:${DB_PASSWORD}@${DB_ENDPOINT}:5432/cargaexpress"
cd backend
uv run alembic upgrade head
uv run alembic check
```

Tambien puedes utilizar el script automatizado `scripts/migrate_rds.sh` (o `scripts/migrate_rds.ps1`):

```bash
# En Linux/macOS
chmod +x scripts/migrate_rds.sh
./scripts/migrate_rds.sh --host "$DB_ENDPOINT" --user postgres --password "$DB_PASSWORD" --name cargaexpress

# En Windows PowerShell
.\scripts\migrate_rds.ps1 -Host $DB_ENDPOINT -User postgres -Password $DB_PASSWORD -Name cargaexpress
```

---

## Paso 3: Configuracion de secretos en AWS Secrets Manager y SSM Parameter Store

El backend lee credenciales sensibles y configuraciones de conexion mediante inyeccion de secretos en la definicion de tarea de ECS.

### 1. Almacenar secretos en AWS Secrets Manager

```bash
# 1. DATABASE_URL para el conector asyncpg de SQLAlchemy
DB_ASYNC_URL="postgresql+asyncpg://postgres:${DB_PASSWORD}@${DB_ENDPOINT}:5432/cargaexpress"
aws secretsmanager create-secret \
  --name "cargaexpress/production/DATABASE_URL" \
  --description "Cadena de conexion asincrona a PostgreSQL RDS" \
  --secret-string "$DB_ASYNC_URL" \
  --region $AWS_REGION

# 2. Clave de administrador para HU-12 y HU-15 (minimo 32 caracteres)
ADMIN_TOKEN=$(openssl rand -hex 32)
aws secretsmanager create-secret \
  --name "cargaexpress/production/ADMIN_API_KEY" \
  --description "Token de autenticacion para endpoints administrativos" \
  --secret-string "$ADMIN_TOKEN" \
  --region $AWS_REGION

# 3. Clave general de API
CLIENT_API_KEY=$(openssl rand -hex 24)
aws secretsmanager create-secret \
  --name "cargaexpress/production/API_KEY" \
  --description "Clave de API para clientes generales" \
  --secret-string "$CLIENT_API_KEY" \
  --region $AWS_REGION

# 4. Mapeo de marcas autenticadas (JSON)
aws secretsmanager create-secret \
  --name "cargaexpress/production/BRAND_API_KEYS" \
  --description "Mapeo JSON de API keys hacia brand_id" \
  --secret-string '{"brand-key-acme-prod": 1, "brand-key-solon-prod": 2}' \
  --region $AWS_REGION

# 5. Cadena de conexion a RabbitMQ
RABBITMQ_PASS=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9')
aws secretsmanager create-secret \
  --name "cargaexpress/production/RABBITMQ_URL" \
  --description "URL de conexion AMQP a RabbitMQ" \
  --secret-string "amqp://cargaexpress:${RABBITMQ_PASS}@rabbitmq.internal:5672/" \
  --region $AWS_REGION
```

### 2. Parametros operativos en SSM Parameter Store

```bash
aws ssm put-parameter --name "/cargaexpress/production/APP_ENV" --value "production" --type String --overwrite
aws ssm put-parameter --name "/cargaexpress/production/LOG_LEVEL" --value "INFO" --type String --overwrite
aws ssm put-parameter --name "/cargaexpress/production/SQL_ECHO" --value "false" --type String --overwrite
aws ssm put-parameter --name "/cargaexpress/production/STATE_MAPPING_CACHE_TTL_SECONDS" --value "300" --type String --overwrite
```

---

## Paso 4: Creacion del cluster ECS, roles IAM y servicios Fargate

### 1. Crear el cluster ECS

```bash
aws ecs create-cluster \
  --cluster-name "${PROJECT_NAME}-cluster" \
  --settings name=containerInsights,value=enabled \
  --region $AWS_REGION
```

### 2. Crear grupos de logs en Amazon CloudWatch

```bash
aws logs create-log-group --log-group-name "/ecs/${PROJECT_NAME}-backend" --region $AWS_REGION
aws logs put-retention-policy --log-group-name "/ecs/${PROJECT_NAME}-backend" --retention-in-days 30 --region $AWS_REGION

aws logs create-log-group --log-group-name "/ecs/${PROJECT_NAME}-worker" --region $AWS_REGION
aws logs put-retention-policy --log-group-name "/ecs/${PROJECT_NAME}-worker" --retention-in-days 30 --region $AWS_REGION
```

### 3. Configurar roles IAM de ejecucion y de tarea

El rol de ejecucion (`executionRoleArn`) permite al agente de ECS descargar imagenes de ECR, enviar logs a CloudWatch y extraer secretos de Secrets Manager. El rol de tarea (`taskRoleArn`) otorga permisos al contenedor en ejecucion.

```bash
# 1. Crear ecsTaskExecutionRole si no existe
cat << 'EOF' > /tmp/ecs-trust-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name "${PROJECT_NAME}-ecs-execution-role" \
  --assume-role-policy-document file:///tmp/ecs-trust-policy.json

aws iam attach-role-policy \
  --role-name "${PROJECT_NAME}-ecs-execution-role" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"

# 2. Agregar politica inline para acceso a Secrets Manager
cat << EOF > /tmp/secrets-policy.json
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
        "arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:cargaexpress/production/*",
        "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/cargaexpress/production/*"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${PROJECT_NAME}-ecs-execution-role" \
  --policy-name "CargaExpressReadSecretsPolicy" \
  --policy-document file:///tmp/secrets-policy.json

# 3. Crear rol de tarea
aws iam create-role \
  --role-name "${PROJECT_NAME}-backend-task-role" \
  --assume-role-policy-document file:///tmp/ecs-trust-policy.json
```

### 4. Registrar Task Definitions desde plantillas

Las definiciones de tarea estan versionadas en `deploy/aws/task-definition-backend.json` y `deploy/aws/task-definition-worker.json`. Se reemplaza `<AWS_ACCOUNT_ID>` antes del registro:

```bash
# Generar archivos con ID de cuenta sustituido
sed "s/<AWS_ACCOUNT_ID>/${AWS_ACCOUNT_ID}/g" deploy/aws/task-definition-backend.json > /tmp/task-backend.json
sed "s/<AWS_ACCOUNT_ID>/${AWS_ACCOUNT_ID}/g" deploy/aws/task-definition-worker.json > /tmp/task-worker.json

# Registrar definiciones en ECS
aws ecs register-task-definition --cli-input-json file:///tmp/task-backend.json --region $AWS_REGION
aws ecs register-task-definition --cli-input-json file:///tmp/task-worker.json --region $AWS_REGION
```

### 5. Crear el servicio de Background Worker (consumidor de RabbitMQ)

El servicio `worker` ejecuta `python -m app.worker` para procesar eventos asincronos sin exposicion directa a red publica:

```bash
aws ecs create-service \
  --cluster "${PROJECT_NAME}-cluster" \
  --service-name "${PROJECT_NAME}-worker-service" \
  --task-definition "cargaexpress-worker" \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIV_SUB_APP_A,$PRIV_SUB_APP_B],securityGroups=[$ECS_SG],assignPublicIp=DISABLED}" \
  --region $AWS_REGION
```

---

## Paso 5: Configuracion del Application Load Balancer (ALB), Target Groups y Health Checks

El balanceador de carga distribuye el trafico externo hacia las tareas Fargate en ejecucion en el puerto 8000.

### 1. Crear el Application Load Balancer

```bash
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name "${PROJECT_NAME}-alb" \
  --subnets "$PUB_SUB_A" "$PUB_SUB_B" \
  --security-groups "$ALB_SG" \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4 \
  --region $AWS_REGION \
  --query "LoadBalancers[0].LoadBalancerArn" --output text)

ALB_DNS=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns "$ALB_ARN" \
  --query "LoadBalancers[0].DNSName" --output text)

echo "ALB Creado. DNS Publico: $ALB_DNS"
```

### 2. Crear Target Group y configurar verificacion de salud

CargaExpress expone dos sondas en `app/routers/health.py`:
- `/api/v1/health`: Sonda de liveness general. Reporta disponibilidad del proceso y diagnostico de la conexion a base de datos.
- `/api/v1/ready`: Sonda de readiness estricta. Ejecuta una consulta de comprobacion activa (`SELECT 1`). Devuelve HTTP 200 unicamente cuando PostgreSQL esta respondiendo y HTTP 503 si la conexion falla.

Para prevenir que el balanceador envie solicitudes a contenedores que no puedan operar contra la base de datos, el Target Group debe monitorear la ruta `/api/v1/ready`:

```bash
TG_ARN=$(aws elbv2 create-target-group \
  --name "${PROJECT_NAME}-backend-tg" \
  --protocol HTTP \
  --port 8000 \
  --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-protocol HTTP \
  --health-check-path "/api/v1/ready" \
  --health-check-interval-seconds 15 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --matcher HttpCode="200" \
  --region $AWS_REGION \
  --query "TargetGroups[0].TargetGroupArn" --output text)
```

### 3. Crear Listener HTTP en el ALB

```bash
aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn="$TG_ARN" \
  --region $AWS_REGION
```

Para entornos productivos con certificado SSL en AWS Certificate Manager (ACM):

```bash
# Ejemplo con certificado ACM existente:
# aws elbv2 create-listener \
#   --load-balancer-arn "$ALB_ARN" \
#   --protocol HTTPS --port 443 \
#   --certificates CertificateArn="arn:aws:acm:us-east-2:${AWS_ACCOUNT_ID}:certificate/<CERT_ID>" \
#   --default-actions Type=forward,TargetGroupArn="$TG_ARN"
```

### 4. Crear el servicio de Backend API en ECS Fargate

Con el Target Group configurado, se instancia el servicio backend con 2 replicas en alta disponibilidad:

```bash
aws ecs create-service \
  --cluster "${PROJECT_NAME}-cluster" \
  --service-name "${PROJECT_NAME}-backend-service" \
  --task-definition "cargaexpress-backend" \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIV_SUB_APP_A,$PRIV_SUB_APP_B],securityGroups=[$ECS_SG],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=${TG_ARN},containerName=backend,containerPort=8000" \
  --health-check-grace-period-seconds 60 \
  --region $AWS_REGION
```

### 5. Verificacion operativa de salud y conectividad

Una vez que las tareas de Fargate transicionen a estado `HEALTHY` en el Target Group:

```bash
# 1. Comprobar liveness probe
curl -i "http://${ALB_DNS}/api/v1/health"

# Respuesta esperada:
# HTTP/1.1 200 OK
# Content-Type: application/json
# {"status":"ok","database":"up"}

# 2. Comprobar readiness probe
curl -i "http://${ALB_DNS}/api/v1/ready"

# Respuesta esperada:
# HTTP/1.1 200 OK
# Content-Type: application/json
# {"status":"ok","database":"up"}

# 3. Comprobar especificacion OpenAPI de endpoints
curl -s "http://${ALB_DNS}/openapi.json" | grep -o '"title":"CargaExpress Control Tower API"'
```

---

## Paso 6: Configuracion de OIDC en GitHub y activacion del pipeline CI/CD

El flujo de despliegue continuo en `.github/workflows/deploy-aws.yml` utiliza OpenID Connect (OIDC) para autenticarse contra AWS sin almacenar claves de acceso estaticas en GitHub.

### 1. Configurar el proveedor OIDC en AWS IAM

Si tu cuenta de AWS no tiene registrado el proveedor de identidad de GitHub:

```bash
aws iam create-open-id-connect-provider \
  --url "https://token.actions.githubusercontent.com" \
  --client-id-list "sts.amazonaws.com" \
  --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1" "1c58761a25e7582c350311a6c40e59a67448373b"
```

### 2. Crear rol IAM con politica de confianza restringida

Reemplaza `cargaexpress/control_tower` por la organizacion y nombre exacto de tu repositorio en GitHub:

```bash
GITHUB_REPO="cargaexpress/control_tower"

cat << EOF > /tmp/github-oidc-trust.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_REPO}:*"
        }
      }
    }
  ]
}
EOF

ROLE_ARN=$(aws iam create-role \
  --role-name "${PROJECT_NAME}-github-deploy-role" \
  --assume-role-policy-document file:///tmp/github-oidc-trust.json \
  --query "Role.Arn" --output text)
```

### 3. Adjuntar permisos minimos de despliegue al rol

```bash
cat << EOF > /tmp/github-deploy-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "arn:aws:ecr:${AWS_REGION}:${AWS_ACCOUNT_ID}:repository/${PROJECT_NAME}/backend"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecs:DescribeTasks",
        "ecs:RegisterTaskDefinition",
        "ecs:UpdateService"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${PROJECT_NAME}-ecs-execution-role",
        "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${PROJECT_NAME}-backend-task-role"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${PROJECT_NAME}-github-deploy-role" \
  --policy-name "CargaExpressGitHubActionsPolicy" \
  --policy-document file:///tmp/github-deploy-policy.json
```

### 4. Configurar secretos en el repositorio de GitHub

En la interfaz de GitHub de tu repositorio, navega a **Settings > Secrets and variables > Actions** y define:

| Nombre del secreto | Valor |
|---|---|
| `AWS_ROLE_TO_ASSUME` | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/cargaexpress-github-deploy-role` |

El archivo `.github/workflows/deploy-aws.yml` incluido en el repositorio compilara automaticamente la imagen ante cada push a la rama `main`, actualizara las definiciones de tarea y aplicara el rolling update en los servicios ECS sin interrumpir el servicio.

---

## Procedimientos de contingencia y rollback

### 1. Reversion rapida a una version previa de tarea en ECS

Si una version recien desplegada presenta fallas imprevistas, revierte el servicio a la revision previa de la definicion de tarea sin esperar un nuevo commit:

```bash
# Listar las ultimas 5 revisiones de la definicion de tarea
aws ecs list-task-definitions --family-prefix cargaexpress-backend --sort DESC --max-items 5

# Actualizar el servicio backend a la revision estable anterior (ejemplo revision 3)
aws ecs update-service \
  --cluster "${PROJECT_NAME}-cluster" \
  --service "${PROJECT_NAME}-backend-service" \
  --task-definition "cargaexpress-backend:3" \
  --region $AWS_REGION
```

### 2. Inspeccion de logs en tiempo real

Para examinar las excepciones o trazas del backend y worker:

```bash
# Ver ultimos logs del backend
aws logs tail "/ecs/${PROJECT_NAME}-backend" --follow --region $AWS_REGION

# Ver ultimos logs del worker
aws logs tail "/ecs/${PROJECT_NAME}-worker" --follow --region $AWS_REGION
```

### 3. Escalar temporalmente el servicio

Para absorber picos de carga durante eventos masivos de ingesta:

```bash
aws ecs update-service \
  --cluster "${PROJECT_NAME}-cluster" \
  --service "${PROJECT_NAME}-backend-service" \
  --desired-count 4 \
  --region $AWS_REGION
```
