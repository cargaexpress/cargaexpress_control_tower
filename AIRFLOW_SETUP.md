# Guía de Despliegue y Operación de Airflow con CeleryExecutor y RabbitMQ

Este documento detalla la arquitectura, configuración y pasos operativos para el entorno de orquestación distribuida de **CargaExpress (Sprint 3)**, cubriendo:
- **HU-26 (RIWI-131)**: Set up Airflow in Docker
- **HU-27 (RIWI-135)**: Pull polling DAG for type-B carriers (F4 - Cada 30 min con TaskFlow API y reintentos)
- **HU-28 (RIWI-139)**: Type-C file ingestion DAG (F5 - Procesamiento batch cada 4 h con sanitización)
- **HU-29 (RIWI-143)**: Configure CeleryExecutor in Airflow connected to RabbitMQ
- **HU-30 (RIWI-147)**: Scale workers and validate distributed execution (Entregable E-12: Runbook Operativo y Escalado)

---

## 1. Arquitectura de Servicios

El stack está orquestado mediante `docker-compose.airflow.yml` y convive en la red `cargaexpress`:

```
+-----------------------------------------------------------------------------------+
| Red Docker: control_tower_cargaexpress                                            |
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
|                      |  (PostgreSQL 16 dedicado) |                                |
|                      |   Puerto local: 5433      |                                |
|                      +---------------------------+                                |
+-----------------------------------------------------------------------------------+
```

### Componentes:
1. **RabbitMQ (`rabbitmq:3-management-alpine`)**: Message Broker para Celery. Expone puerto 5672 para comunicación AMQP y 15672 para la consola web de gestión.
2. **Airflow DB (`airflow-db`)**: Base de datos dedicada de PostgreSQL 16 para el metastore de Airflow, aislada del WMS operacional. Expuesta en host: `5433`.
3. **Airflow Init (`airflow-init`)**: Contenedor transitorio que ejecuta migraciones (`airflow db migrate`) y asegura el usuario administrador inicial.
4. **Airflow Webserver (`airflow-webserver`)**: UI administrativa de Airflow en el puerto `8080`.
5. **Airflow Scheduler (`airflow-scheduler`)**: Planificador y monitor del ciclo de vida de los DAGs con `CeleryExecutor`.
6. **Airflow Worker (`airflow-worker`)**: Proceso Celery Worker que consume tareas concurrentes encoladas en RabbitMQ. Admite escalado horizontal nativo sin colisión de nombres.
7. **Volúmenes Mapeados**:
   - `./dags`: Directorio de DAGs montado en `/opt/airflow/dags`.
   - `./logs`: Logs de ejecución montados en `/opt/airflow/logs`.
   - `./plugins`: Plugins personalizados montados en `/opt/airflow/plugins`.
   - `./data`: Archivos de entrada/salida montados en `/opt/airflow/data`.

---

## 2. Convenciones de Diseño: TaskFlow API y Modularización

Alineado con los estándares del proyecto (TaskFlow API en inglés y separación de responsabilidades):

1. **Paradigma TaskFlow (@dag y @task)**:
   - Se reemplazó el uso clásico de `PythonOperator` por decoradores `@dag` y `@task`.
   - Los datos fluyen como argumentos y valores de retorno entre tareas sin manipulación manual de XComs.
2. **Modularización y Reutilización**:
   - Los DAGs no contienen consultas SQL crudas ni lógica de negocio acoplada.
   - La orquestación interactúa con los servicios oficiales de ingesta a través del cliente modular `dags/utils/control_tower_client.py` (`ControlTowerClient`), reutilizando los conectores Tipo B (`POST /api/v1/sync/type-b`) y Tipo C (`POST /api/v1/sync/type-c/upload`) construidos en Sprint 2.
3. **Idioma 100% Inglés**:
   - Docstrings, nombres de tareas, variables, logs y excepciones están estandarizados en inglés.

---

## 3. Instrucciones para Levantar el Stack

### Paso 1: Configurar Variables de Entorno (Opcional)
Si deseas ajustar credenciales o puertos, copia `.env.example` a `.env` o define las variables:
```bash
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=admin
_AIRFLOW_WWW_USER_PASSWORD=admin
CONTROL_TOWER_API_URL=http://backend:8000
AIRFLOW_WORKER_REPLICAS=2
```

### Paso 2: Inicializar la Base de Datos de Airflow
```bash
docker compose -f docker-compose.airflow.yml up airflow-init
```

### Paso 3: Iniciar los Servicios de Airflow y RabbitMQ
```bash
docker compose -f docker-compose.airflow.yml up -d
```
*Por defecto, se inician automáticamente 2 instancias worker de Celery (`control_tower-airflow-worker-1` y `control_tower-airflow-worker-2`).*

Verificar que los servicios estén saludables (`healthy`):
```bash
docker compose -f docker-compose.airflow.yml ps
```

---

## 4. DAGs de Ingesta y Validación

### A. Pipeline de Polling Tipo B (`type_b_pull_polling`) - HU-27 (RIWI-135)
Ejecuta la ingesta periódica por consulta REST (Pull) contra los 4 carriers Tipo B:
- **Schedule**: `*/30 * * * *` (cada 30 minutos).
- **Resiliencia**: 3 reintentos con backoff exponencial (`retry_exponential_backoff=True`) y límite de 20 minutos para absorber rate limits de transportadoras.
- **Flujo**:
  1. `verify_backend_readiness`: Comprueba que el backend esté listo.
  2. `poll_type_b_carriers`: Invoca `POST /api/v1/sync/type-b` para consultar APIs REST, normalizar estados a RN-02 y actualizar WMS.
  3. `evaluate_polling_metrics`: Consolida eventos normalizados, anomalías detectadas y emite alertas en caso de errores.

### B. Pipeline de Archivos Lote Tipo C (`type_c_file_ingestion`) - HU-28 (RIWI-139)
Procesa archivos por lotes (CSV/XLSX) depositados en `data/type_C_simulation_data/`:
- **Schedule**: `0 */4 * * *` (cada 4 horas).
- **Flujo**:
  1. `scan_incoming_files`: Detecta archivos entrantes `.csv` y `.xlsx` no temporales.
  2. `ingest_batch_files`: Infiere la transportadora y envía el archivo a `POST /api/v1/sync/type-c/upload`, donde se descartan cabeceras duplicadas, se eliminan filas de totales, se valida el hash SHA-256 de idempotencia y se normalizan los eventos.
  3. `archive_processed_files`: Mueve los archivos procesados exitosamente al subdirectorio `processed/` con prefijo timestamp.

### C. Pipeline de Validación Distribuida (`dag_distributed_validation`) - HU-30 (RIWI-147)
Valida y audita formalmente la distribución paralela de tareas a través de Celery y RabbitMQ:
- **Flujo**:
  1. `init_distributed_test`: Inicializa metadatos globales de la prueba.
  2. `worker_probe_partition_[1..4]`: 4 tareas paralelas (fan-out) concurrentes que capturan hostname, PID, IP y timestamps de cada worker Celery.
  3. `aggregate_distributed_evidence`: Tarea fan-in que consolida XComs y emite dictamen formal de auditoría distribuida.

---

## 5. Escalado Horizontal de Workers y Ejecución Distribuida (HU-30 / RIWI-147)

### 5.1 Mecanismo de Escalabilidad
En `docker-compose.airflow.yml`, el servicio `airflow-worker` no fija un `container_name` estático, lo que habilita la escalabilidad horizontal nativa de Docker Compose sin colisiones de nombres.

#### Escalar a N Workers en Caliente:
```bash
# Escalar a 3 workers concurrentes
docker compose -f docker-compose.airflow.yml up -d --scale airflow-worker=3

# Reescalar a 2 workers
docker compose -f docker-compose.airflow.yml up -d --scale airflow-worker=2
```

---

## 6. Runbook Operativo de Verificación y Troubleshooting (Entregable E-12)

### 6.1 Auditoría de Ejecución Distribuida
```bash
# Disparar prueba de validación distribuida
docker compose -f docker-compose.airflow.yml exec airflow-webserver airflow dags trigger dag_distributed_validation

# Ver logs del consolidador fan-in
docker compose -f docker-compose.airflow.yml exec airflow-webserver airflow tasks logs dag_distributed_validation aggregate_distributed_evidence
```

### 6.2 Verificación en Celery y RabbitMQ
```bash
# Ping a todos los workers activos en Celery
docker compose -f docker-compose.airflow.yml exec airflow-scheduler celery --app airflow.providers.celery.executors.celery_executor.app inspect ping

# Tareas activas en cada worker
docker compose -f docker-compose.airflow.yml exec airflow-scheduler celery --app airflow.providers.celery.executors.celery_executor.app inspect active

# Listar colas y consumidores en RabbitMQ
docker compose -f docker-compose.airflow.yml exec rabbitmq rabbitmqctl list_queues name messages consumers
```

Verificación en RabbitMQ Web UI:
1. Abrir [http://localhost:15672](http://localhost:15672) (credenciales `guest` / `guest`).
2. Pestaña **Queues**: cola `default` de Celery debe mostrar el número de consumidores coincidente con los workers escalados.

---

## 7. Pruebas y Validación Automatizada

### Pruebas de Integridad de DAGs con Pytest
```bash
cd backend
uv run pytest tests/test_dags.py -v
```

### Validar Sintaxis de los DAGs
```bash
python -m py_compile dags/dag_type_b_polling.py
python -m py_compile dags/dag_type_c_ingestion.py
python -m py_compile dags/dag_distributed_validation.py
```

### Detener el Stack
```bash
docker compose -f docker-compose.airflow.yml down
```
*(Para limpiar también los volúmenes de datos, agrega la bandera `-v`).*
