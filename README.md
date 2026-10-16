# CargaExpress Control Tower

Backend API para la torre de control de CargaExpress. Usa FastAPI, SQLAlchemy,
Alembic y PostgreSQL.

## Estado actual

- API disponible en `http://localhost:8000`.
- Documentación interactiva de la API en `http://localhost:8000/docs`.
- Health check en `GET /api/v1/health`.
- Modelos y migraciones para 11 tablas WMS más `state_mapping`.
- Revisión Alembic actual: `f6b2a9d14c83`.
- Seed inicial de tres transportadoras simuladas y sus mapeos canónicos; no hay
  órdenes de ejemplo.
- **HU-12 — Mapeo de estados:** API administrativa con caché invalidable y
  cambios visibles sin reiniciar. Ver [detalle de HU-12](./STATE_MAPPING.md).
- **HU-13 — Pedidos / Orders:** API para crear pedidos con líneas y destinatario,
  consultarlos por ID, listarlos con paginación y actualizar su estado.
  Endpoints bajo `/api/v1/orders`; pruebas de integración en
  `backend/tests/test_orders.py`.
- **RN-07 — Pedidos Divididos en Múltiples Guías:** Endpoints para asociar (`POST`)
  y listar (`GET`) guías vinculadas a un pedido bajo `/api/v1/orders/{order_id}/shipping-labels`,
  con aislamiento multitenant derivado de `X-API-Key` y `BRAND_API_KEYS`; el
  header `X-Brand-Id` no determina el tenant. `tracking_number` es único globalmente.
- Las reglas para impedir retrocesos desde estados terminales y registrar
  anomalías (RN-02) todavía no están implementadas.

## Requisitos

Para ejecutar el proyecto con Docker:

- Docker Desktop instalado y en ejecución.
- Docker Compose v2 (`docker compose`).
- Puertos `8000` y `5432` disponibles, o configurar puertos alternativos en `.env`.

No hace falta instalar Python, uv ni PostgreSQL en la máquina para usar Docker.
Compose entrega `DATABASE_URL` al backend usando las credenciales del `.env` y el
nombre de host `db` de la red interna. La aplicación no trae una URL de base de
datos por defecto: sin esa variable no inicia.

Compose no instala librerías directamente; construye la imagen desde el
`backend/Dockerfile`. El servicio `backend` en `docker-compose.yml` deja anotado
el inventario de dependencias runtime: FastAPI, Uvicorn, SQLAlchemy, asyncpg,
Alembic y Pydantic Settings. La lista instalable autoritativa está en
`backend/pyproject.toml`, queda fijada en `backend/uv.lock` y el Dockerfile la
instala con `uv sync --frozen --no-dev` al construir la imagen.

## Ejecutar el proyecto con Docker

Ejecuta los siguientes comandos desde la raíz del repositorio, donde está
`docker-compose.yml`.

### 1. Configurar el entorno

La primera vez, crea el archivo `.env` en la raíz copiando la plantilla. En
PowerShell:

```powershell
Copy-Item .env.example .env
```

Si `.env` ya existe, conserva tus valores y verifica que incluya al menos:

```env
POSTGRES_USER=cargaexpress
POSTGRES_PASSWORD=change_me_local_only
POSTGRES_DB=cargaexpress
BACKEND_PORT=8000
DB_PORT=5432
APP_ENV=development
SQL_ECHO=false
ADMIN_API_KEY=
API_KEY=
BRAND_API_KEYS={}
LOG_LEVEL=INFO
STATE_MAPPING_CACHE_TTL_SECONDS=300
```

Reemplaza `change_me_local_only` por una contraseña propia. No guardes
credenciales reales en el repositorio; `.env` está ignorado por Git.
`POSTGRES_USER` y `POSTGRES_PASSWORD` son obligatorias. Las demás variables son
opcionales y tienen valores predeterminados en `docker-compose.yml`.
`API_KEY` configura la clave compartida. Para los endpoints de pedidos y guías,
configura `BRAND_API_KEYS` como un objeto JSON que asocia cada clave API con su
`brand_id`, por ejemplo `{"<clave-segura-de-marca-a>":1,"<clave-segura-de-marca-b>":2}`.
El tenant se obtiene de `X-API-Key`; ni `X-Brand-Id` ni el `brand_id` enviado en
el cuerpo pueden cambiarlo. `LOG_LEVEL` acepta `DEBUG`, `INFO`, `WARNING`,
`ERROR` o `CRITICAL` y su valor predeterminado es `INFO`.
Configura `ADMIN_API_KEY` con una clave propia para habilitar los endpoints
administrativos; si está vacía, estos responden `503`.
En producción, `API_KEY`, `ADMIN_API_KEY` y cada clave de `BRAND_API_KEYS` deben
tener al menos 32 caracteres y no comenzar con `change_me`.

### 2. Levantar todo con un comando

```powershell
docker compose up
```

Compose reconstruye la imagen del backend, levanta los dos servicios y espera a
que PostgreSQL esté listo:

- `backend`: API FastAPI en el puerto `8000`.
- `db`: PostgreSQL 16 en el puerto `5432`.

Antes de iniciar FastAPI, el backend ejecuta `alembic upgrade head`
automáticamente. No hace falta ejecutar un comando separado para crear las
tablas.

### 3. Verificar que funciona

Las siguientes verificaciones se ejecutan en otra terminal mientras
`docker compose up` sigue activo. Revisión aplicada:

```powershell
docker compose exec backend alembic current
```

Debe mostrar:

```text
f6b2a9d14c83 (head)
```

Comprobar el estado del API:

```powershell
curl.exe http://localhost:8000/api/v1/health
```

Respuesta esperada:

```json
{"status":"ok","database":"up"}
```

Comprobar que existen las tablas:

```powershell
docker compose exec db psql -U cargaexpress -d cargaexpress -c "\dt"
```

Se esperan 12 tablas de la aplicación y `alembic_version`. El seed agrega tres
transportadoras simuladas y sus mapeos; no se crean órdenes de ejemplo. Para
abrir una consola SQL interactiva:

```powershell
docker compose exec db psql -U cargaexpress -d cargaexpress
```

Dentro de `psql` puedes usar:

```sql
\dt
\d orders
SELECT * FROM orders;
\q
```

### 4. Ver la base de datos visualmente

Puedes conectarte con DBeaver o con una extensión PostgreSQL para VS Code:

| Campo | Valor |
|---|---|
| Host | `localhost` |
| Puerto | El valor de `DB_PORT` (por defecto `5432`) |
| Base de datos | El valor de `POSTGRES_DB` (por defecto `cargaexpress`) |
| Usuario | El valor de `POSTGRES_USER` |
| Contraseña | El valor de `POSTGRES_PASSWORD` |

En DBeaver, abre la conexión y navega a `Schemas > public > Tables`. Usa
**View Data** sobre `carriers` o `state_mapping` para ver las filas del seed.
Las tablas de órdenes y operación comienzan sin registros de ejemplo.

## Reflejar cambios de código y de base de datos

Compose **no monta el código fuente como volumen**. `docker compose up`
reconstruye la imagen del backend y vuelve a aplicar las migraciones pendientes
antes de iniciar FastAPI, así que refleja los cambios de código y esquema. La
construcción usa la caché de Docker para reutilizar las capas sin cambios.

```powershell
docker compose up
```

Después de cambiar modelos o el esquema:

1. Crea y revisa una nueva migración de Alembic en `backend/alembic/versions/`.
2. Ejecuta `docker compose up`. Compose reconstruye el backend y su arranque
   aplica automáticamente las migraciones pendientes.
3. Verifica con `docker compose exec backend alembic current` y el health check.

Para generar una migración automáticamente desde los modelos, necesitas Python
3.12 y uv. Desde `backend`, configura `DATABASE_URL` para conectarse a PostgreSQL
desde el host (`localhost`, puerto `DB_PORT` y las credenciales del `.env` raíz).
Dentro de Docker la aplicación usa el host `db`; desde el host usa `localhost`.

```powershell
cd backend
uv run alembic revision --autogenerate -m "describe el cambio"
cd ..
docker compose up
```

La base de datos usa el volumen nombrado `postgres_data`. `docker compose down`
detiene y elimina los contenedores, pero conserva los datos. **No uses
`docker compose down -v` salvo que quieras borrar también la base de datos.**

## Servicios y modelos incluidos

### HU-13 — Pedidos / Orders

La API expone estas operaciones bajo `/api/v1/orders`:

- `POST /api/v1/orders`: crea un pedido junto con sus líneas y destinatario;
  comprueba que existan la marca, el centro de distribución y el tipo de envío.
- `GET /api/v1/orders/{order_id}`: consulta un pedido por ID.
- `GET /api/v1/orders?skip=0&limit=50`: lista pedidos con paginación.
- `PATCH /api/v1/orders/{order_id}/status`: actualiza el estado del pedido.

La integración se probó con la suite ejecutada en Docker. La actualización de
estado es directa; todavía no aplica RN-02 para impedir retrocesos desde estados
terminales ni registra anomalías.

La migración inicial crea:

- `brands`
- `carriers`
- `distribution_centers`
- `shipment_types`
- `dispatches`
- `orders`
- `order_lines`
- `order_recipients`
- `shipping_labels`
- `picking_tasks`
- `shipping_label_items`
- `state_mapping` (agregada por las migraciones de HU-12)

Los modelos SQLAlchemy están en `backend/app/models/`; las migraciones, en
`backend/alembic/versions/`. Alembic registra esos modelos desde
`backend/alembic/env.py`.

La migración `f6b2a9d14c83` agrega unicidad global a
`shipping_labels.tracking_number` y unicidad por marca a
`(orders.brand_id, orders.brand_order_ref)`. También crea índices para
`orders.brand_id`, `orders.status`, `shipping_labels.order_id` y
`shipping_labels.carrier_id`. Antes de crear las restricciones, la migración
falla con instrucciones claras si encuentra duplicados existentes; deduplica
esos datos y vuelve a ejecutar la migración.

## Comandos útiles

```powershell
docker compose ps
docker compose logs -f backend
docker compose logs -f db
docker compose stop
docker compose down
```

### Ejecutar las pruebas dentro de Docker

No es necesario crear ni activar `.venv` en la máquina. Desde la raíz del
repositorio, con las variables de base de datos configuradas en `.env`, ejecuta:

```powershell
docker compose --profile test up --build --abort-on-container-exit --exit-code-from test test
```

Docker construye una imagen de pruebas con las dependencias de desarrollo,
inicia una PostgreSQL aislada para tests, restablece sus migraciones y ejecuta
`pytest` para `backend/tests/` y las pruebas raíz de `tests/`, incluyendo los
simuladores. Antes de pytest ejecuta `alembic upgrade head` y `alembic check`
para detectar drift entre las migraciones y los modelos. No borra ni modifica
la base de datos normal del proyecto.
Las dependencias de prueba no se incluyen en la imagen del backend de producción.

Para detener y además borrar los datos persistidos:

```powershell
docker compose down -v
```

## Desarrollo local opcional

Para ejecutar el backend fuera de Docker, instala Python 3.12 y uv. Desde
`backend`, crea un archivo `.env` ignorado por Git y configura ahí la variable
obligatoria `DATABASE_URL` con las credenciales y dirección de tu instancia
local de PostgreSQL. No escribas esa URL con credenciales en el código ni la
compartas. Luego, desde `backend`:

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

Configura `backend/.env` con la URL apropiada y asegúrate de tener PostgreSQL
disponible. Desde `backend`, ejecuta las comprobaciones de lint, formato y tipos:

```powershell
uv sync --frozen
uv run ruff check --config pyproject.toml app tests ../simulators ../tests ../scripts
uv run ruff format --config pyproject.toml --check app tests ../simulators ../tests ../scripts
uv run mypy app
```

Para pruebas locales, configura `DATABASE_URL` y `TEST_DATABASE_URL` para una
base PostgreSQL **aislada de pruebas**; ambas deben apuntar a esa base para
aplicar las migraciones y ejecutar los tests:

```powershell
uv run alembic upgrade head
uv run alembic check
uv run pytest -v --cov=app --cov-report=term-missing --cov-fail-under=80 tests ../tests
```

## Estructura principal

```text
.
├── backend/
│   ├── app/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── services/
│   ├── alembic/
│   │   └── versions/
│   ├── tests/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── uv.lock
├── simulators/
├── tests/
├── scripts/
├── docs/
│   └── api/
│       └── openapi.json
├── docker-compose.yml
└── README.md
```
