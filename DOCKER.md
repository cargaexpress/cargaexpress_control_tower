# Dockerización del backend — US-07

**Historia:** Dockerize the First Backend Component
**Subtareas:** RIWI-41 (Dockerfile con variables de entorno) · RIWI-42 (docker-compose.yml backend + PostgreSQL)

---

## 1. Archivos nuevos

| Archivo | Para qué sirve | Subtarea |
|---|---|---|
| `backend/Dockerfile` | Construye la imagen del backend (Python 3.12 + uv, multi-etapa, usuario sin privilegios, healthcheck). No contiene credenciales. | RIWI-41 |
| `backend/.dockerignore` | Evita copiar `.venv`, `.env`, tests y basura a la imagen. | RIWI-41 |
| `docker-compose.yml` | Levanta `backend` (FastAPI) + `db` (PostgreSQL 16) con red, volumen y healthchecks. | RIWI-42 |
| `.env.example` | Plantilla de variables de entorno. Se copia a `.env` (que no se sube a git). | RIWI-41 / 42 |
| `.gitignore` | Evita subir el `.env` con credenciales reales. | Criterio 2 |
| `verificar.sh` | Script que comprueba automáticamente los 3 criterios de aceptación. | Evidencia |
| `DOCKER.md` | Esta documentación. | — |

Archivo modificado: `README.md` (se agregó la sección "Ejecutar con Docker").
**El código de la aplicación (`backend/app`, `alembic`, tests) no fue modificado.**

---

## 2. Cómo ejecutarlo

Requisitos: Docker y Docker Compose. No hace falta Python, uv ni PostgreSQL instalados.

```bash
# 1) Entrar a la carpeta del repositorio
cd cargaexpress_control_tower-main

# 2) Crear el archivo de variables y editar la contraseña local
cp .env.example .env

# 3) Construir, levantar todo y aplicar migraciones automáticamente
docker compose up

# 4) Probar (en otra terminal)
curl http://localhost:8000/api/v1/health
# → {"status":"ok","database":"up"}
```

Swagger: http://localhost:8000/docs

### Comandos útiles

```bash
docker compose up -d              # en segundo plano; también construye la imagen
docker compose ps                # estado de los servicios
docker compose logs -f backend   # ver logs del backend
docker compose down              # detener (conserva los datos)
docker compose down -v           # detener y borrar la base de datos
./verificar.sh                   # comprobar los criterios de aceptación
```

### Variables de entorno (`.env`)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `POSTGRES_USER` | Sí | Usuario de PostgreSQL |
| `POSTGRES_PASSWORD` | Sí | Contraseña de PostgreSQL |
| `POSTGRES_DB` | No (`cargaexpress`) | Nombre de la base |
| `APP_ENV` | No (`development`) | Entorno de la app |
| `SQL_ECHO` | No (`false`) | Log de consultas SQL |
| `BACKEND_PORT` | No (`8000`) | Puerto del backend en tu máquina |
| `DB_PORT` | No (`5432`) | Puerto de PostgreSQL en tu máquina |

Si faltan `POSTGRES_USER` o `POSTGRES_PASSWORD`, `docker compose` se detiene con un mensaje claro.
Usa una contraseña local sin caracteres reservados de URL (`@ : / # ?`) o codifícalos, porque las credenciales se interpolan en `DATABASE_URL`.

---

## 3. Cumplimiento de la historia

### Subtareas

| Subtarea | Estado | Cómo se cumple |
|---|---|---|
| **RIWI-41** Create backend Dockerfile using environment variables | ✅ | `backend/Dockerfile`: la configuración (`DATABASE_URL`, `APP_ENV`, `SQL_ECHO`) llega por variables de entorno al ejecutar el contenedor; el Dockerfile no define ninguna. |
| **RIWI-42** Create initial docker-compose.yml (backend + PostgreSQL) | ✅ | `docker-compose.yml`: servicios `backend` y `db`, red compartida, volumen `postgres_data`, `depends_on` con healthcheck; el backend aplica las migraciones al iniciar. |

### Criterios de aceptación

| # | Criterio | Estado | Evidencia |
|---|---|---|---|
| 1 | Con `docker compose up` el backend y PostgreSQL arrancan y el backend se comunica con la base | ✅ | `db` tiene healthcheck (`pg_isready`), `backend` espera a que esté sano y aplica `alembic upgrade head` antes de iniciar. `GET /api/v1/health` devuelve `"database":"up"`. |
| 2 | Configuración y credenciales por variables de entorno, sin datos sensibles en el Dockerfile ni en el código fuente | ✅ | El Dockerfile no tiene credenciales. En `docker-compose.yml` el usuario y la clave son obligatorios y se leen de `.env` (sin valores por defecto escritos). `.env` está en `.gitignore`. Ver la nota de la sección 4. |
| 3 | Portable: otro miembro del equipo ejecuta el compose documentado en otra máquina y funciona sin configuración específica de su equipo | ✅ | Solo requiere Docker + `cp .env.example .env` + `docker compose up`. Compose construye la imagen; el backend usa el host `db` (red de Docker), no `localhost`. Dependencias fijadas por `uv.lock`; imágenes base con versión definida. |

### Entorno de la historia
Docker ✅ · Dockerfile ✅ · Docker-compose ✅

---

## 4. Notas importantes

- **Migraciones (Alembic):** el contenedor ejecuta `alembic upgrade head` en cada inicio antes de lanzar FastAPI; las migraciones ya aplicadas no se vuelven a ejecutar.
- **Producción:** el compose es para desarrollo/pruebas locales. En producción las credenciales deben venir del gestor de secretos del entorno, no de un `.env`.

---

## 5. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `Falta POSTGRES_PASSWORD en el archivo .env` | Crear `.env` (`cp .env.example .env`) y ajustar la contraseña local. |
| `port is already allocated` | Cambiar `BACKEND_PORT` o `DB_PORT` en `.env`. |
| `"database":"down"` | Esperar unos segundos y reintentar; revisar `docker compose logs db`. Si cambiaste la contraseña después de la primera vez, ejecuta `docker compose down -v` para recrear la base. |
| Cambié el código y no se refleja | Vuelve a ejecutar `docker compose up`; el servicio backend está configurado para reconstruir su imagen. |
