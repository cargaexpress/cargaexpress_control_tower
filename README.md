# CargaExpress Control Tower

Backend API para la torre de control de CargaExpress. Usa FastAPI, SQLAlchemy,
Alembic y PostgreSQL.

## Estado actual

- API disponible en `http://localhost:8000`.
- Documentación interactiva de la API en `http://localhost:8000/docs`.
- Health check en `GET /api/v1/health`.
- Modelos y migración inicial para 11 tablas WMS.
- Revisión Alembic actual: `dee4876a63bd`.
- No hay datos de ejemplo (seed): las tablas comienzan vacías.

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
```

Reemplaza `change_me_local_only` por una contraseña propia. No guardes
credenciales reales en el repositorio; `.env` está ignorado por Git.
`POSTGRES_USER` y `POSTGRES_PASSWORD` son obligatorias. Las demás variables son
opcionales y tienen valores predeterminados en `docker-compose.yml`.

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
dee4876a63bd (head)
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

Se esperan 11 tablas de la aplicación y `alembic_version`. Para abrir una
consola SQL interactiva:

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
**View Data** sobre una tabla para consultar sus filas. Las tablas comienzan
vacías hasta que se agreguen datos.

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

Los modelos SQLAlchemy están en `backend/app/models/`; las migraciones, en
`backend/alembic/versions/`. Alembic registra esos modelos desde
`backend/alembic/env.py`.

## Comandos útiles

```powershell
docker compose ps
docker compose logs -f backend
docker compose logs -f db
docker compose stop
docker compose down
```

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
disponible. Para pruebas:

```powershell
uv run pytest -v
```

## Estructura principal

```text
.
├── backend/
│   ├── app/
│   │   └── models/
│   ├── alembic/
│   │   └── versions/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── pyproject.toml
│   └── uv.lock
├── docker-compose.yml
└── README.md
```

`.dockerignore` evita enviar al contexto de build archivos locales como
entornos virtuales, secretos, cachés y pruebas.
