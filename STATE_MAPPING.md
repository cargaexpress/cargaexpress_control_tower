# HU-12 — Mapeo configurable de estados (`state_mapping`)

**Historia:** HU-12 — Create the Configurable State Mapping Model
**Historia de usuario:** *Como equipo backend, quiero crear el modelo de mapeo de estados (RN-01) persistido en la base de datos, para que pueda configurarse sin volver a desplegar el servicio (CA-06).*
**Bloqueada por:** RIWI-52 / HU-11 (modelo ORM del WMS, ya finalizada: se apoya en la tabla `carriers`).

Cada transportadora reporta los envíos con su propio vocabulario (`"En tránsito"`, `"300"`, `"IN_TRANSIT"`…).
La tabla `state_mapping` traduce esos estados a un **estado canónico** único del sistema y se puede cambiar
desde un endpoint admin, sin reiniciar ni desplegar de nuevo.

---

## 1. Cómo se cumplió cada requisito

### Criterio de aceptación

> *A `state_mapping` table exists in the database, is editable through an admin endpoint, and changes are reflected without restarting the service.*

| Parte del criterio | Cómo se cumplió | Dónde está | Cómo se comprobó |
|---|---|---|---|
| **La tabla `state_mapping` existe en la base de datos** | La migración crea la tabla con sus columnas, llave foránea a `carriers` y restricción única. Se aplica sola al iniciar (`alembic upgrade head`, ya incluido en el `Dockerfile`). | `alembic/versions/a3f1c9d27b45_crear_tabla_state_mapping.py` | Migración ejecutada contra PostgreSQL: crea la tabla; `alembic check` responde "No new upgrade operations detected" (modelo y migración coinciden); bajar y subir la migración funciona. |
| **Es editable mediante un endpoint admin** | `POST` (crear), `PATCH` (editar), `DELETE` (borrar) y `GET` (listar) en `/api/v1/admin/state-mappings`, protegidos con el header `X-Admin-Token`. | `app/routers/admin_state_mapping.py`, `app/schemas/state_mapping.py`, `app/security.py` | Probado con un servidor real: crear → 201, editar → 200, borrar → 204, duplicado → 409, transportadora inexistente → 404, estado canónico inválido → 422, sin token → 401, sin clave configurada → 503. |
| **Los cambios se reflejan sin reiniciar el servicio** | Cada crear/editar/borrar avisa a la caché (`invalidate()`) **después** de confirmar en la base de datos; la siguiente consulta recarga y ve el cambio. | `app/services/state_mapping_cache.py`, `app/routers/admin_state_mapping.py` | Con el servidor encendido se editó un mapeo y `resolve` devolvió el valor nuevo de inmediato, sin reinicio. Cubierto por la prueba automática `test_changes_are_reflected_without_restarting`. |

### Historia de usuario

| Punto de la historia | Cómo se cumplió |
|---|---|
| Modelo de mapeo de estados **persistido en la base de datos** (RN-01) | Tabla `state_mapping` en PostgreSQL, con migración de Alembic. |
| **Configurable sin volver a desplegar** (CA-06) | Se edita por endpoint y los cambios se aplican en caliente (ver arriba). |

### Subtareas

| Subtarea | Qué pide | Cómo se cumplió | Archivos |
|---|---|---|---|
| **RIWI-58** | Crear el modelo `StateMapping` (`carrier_id`, `source_status`, `canonical_status`) | Modelo con esas 3 columnas, más `mapping_id` (llave primaria), `created_at` y `updated_at`. Restricción única `(carrier_id, source_status)` para que un estado de una transportadora tenga un solo significado. Migración generada con Alembic. | `app/models/state_mapping.py`, `alembic/versions/a3f1c9d27b45_…` |
| **RIWI-59** | Cargar el seed inicial de mapeo para las transportadoras simuladas | Migración que crea 3 transportadoras simuladas (`SimCarrier Alpha`, `Beta`, `Gamma`) con 9 estados cada una (27 mapeos). Cada una usa un vocabulario distinto: inglés, códigos numéricos y español. Se puede ejecutar varias veces sin duplicar y no pisa cambios hechos luego desde el endpoint. | `alembic/versions/b7e24d51c8a9_seed_state_mapping_…` |
| **RIWI-60** | Cachear el mapeo en memoria con invalidación cuando hay cambios | `StateMappingCache`: carga la tabla una sola vez, responde desde memoria, se invalida tras cada cambio y además expira por tiempo (TTL) como respaldo. Si se invalida justo mientras se está leyendo, esa lectura no se guarda (podría ser anterior al cambio). | `app/services/state_mapping_cache.py` |

### Resultado de las verificaciones

| Verificación | Resultado |
|---|---|
| Migraciones sobre una base vacía (`dee4876a63bd → a3f1c9d27b45 → b7e24d51c8a9`) | ✅ |
| Seed: 3 transportadoras, 27 mapeos; repetirlo no duplica; reutiliza una transportadora que ya exista | ✅ |
| Bajar y subir las migraciones (`downgrade` / `upgrade`) | ✅ |
| `alembic check` (modelo = migración) | ✅ |
| Pruebas automáticas (`pytest`): 17 pasan, incluida la prueba de salud existente | ✅ |
| Prueba de que la invalidación es necesaria (si se quita, la prueba falla) | ✅ |
| Endpoint probado con un servidor real y PostgreSQL | ✅ |
| `docker compose up --build` | ⚠️ No se pudo ejecutar en el entorno de desarrollo (sin Docker). Es la verificación pendiente: ver sección 3. |

---

## 2. Archivos

### Nuevos (están en el zip)

| Archivo | Para qué sirve | Subtarea |
|---|---|---|
| `backend/app/models/state_mapping.py` | Modelo `StateMapping` y lista de estados canónicos | RIWI-58 |
| `backend/alembic/versions/a3f1c9d27b45_crear_tabla_state_mapping.py` | Crea la tabla | RIWI-58 |
| `backend/alembic/versions/b7e24d51c8a9_seed_state_mapping_transportadoras_simuladas.py` | Seed inicial | RIWI-59 |
| `backend/app/services/state_mapping_cache.py` | Caché en memoria con invalidación | RIWI-60 |
| `backend/app/routers/admin_state_mapping.py` | Endpoints admin | RIWI-60 |
| `backend/app/schemas/state_mapping.py` | Validación de entrada y salida | RIWI-60 |
| `backend/app/security.py` | Protección con `ADMIN_API_KEY` | RIWI-60 |
| `backend/tests/test_state_mapping_cache.py` | Pruebas de la caché (sin base de datos) | RIWI-60 |
| `backend/tests/test_admin_state_mapping.py` | Pruebas del endpoint (con PostgreSQL) | RIWI-60 |
| `backend/tests/test_state_mapping_seed.py` | Verifica que el seed use solo estados canónicos válidos | RIWI-59 |
| `STATE_MAPPING.md` | Este documento | — |

### Cambios obligatorios en archivos que ya existen

El zip trae solo archivos nuevos, así que estos **5 archivos existentes** hay que editarlos a mano
(son cambios pequeños). Sin ellos, el endpoint no se registra y la tabla no se detecta.

**1. `backend/app/main.py`** — registrar el router:

```python
from app.routers import admin_state_mapping, health      # antes: from app.routers import health

app.include_router(health.router)
app.include_router(admin_state_mapping.router)           # línea nueva
```

**2. `backend/app/config.py`** — dos variables nuevas dentro de la clase `Settings`, después de `sql_echo`:

```python
    admin_api_key: str = ""
    state_mapping_cache_ttl_seconds: int = 300
```

**3. `backend/app/models/__init__.py`** — debe importar todos los modelos. En el repositorio recibido estaba **vacío**
(sin eso Alembic no detecta las tablas y SQLAlchemy no resuelve las relaciones por nombre). Contenido completo:

```python
from app.models.brand import Brand  # noqa: F401
from app.models.carrier import Carrier  # noqa: F401
from app.models.dispatch import Dispatch  # noqa: F401
from app.models.distribution_center import DistributionCenter  # noqa: F401
from app.models.order import Order  # noqa: F401
from app.models.order_line import OrderLine  # noqa: F401
from app.models.order_recipient import OrderRecipient  # noqa: F401
from app.models.picking_task import PickingTask  # noqa: F401
from app.models.shipment_type import ShipmentType  # noqa: F401
from app.models.shipping_label import ShippingLabel  # noqa: F401
from app.models.shipping_label_item import ShippingLabelItem  # noqa: F401
from app.models.state_mapping import StateMapping  # noqa: F401
```

Si en tu repositorio real ese archivo ya tiene los imports, agrega solo la última línea.

**4. `docker-compose.yml`** — en el servicio `backend`, dentro de `environment`, junto a `SQL_ECHO`:

```yaml
      ADMIN_API_KEY: ${ADMIN_API_KEY:-}
```

**5. `.env.example`** (y tu `.env`) — agregar:

```env
ADMIN_API_KEY=change_me_admin_key
```

Opcional: en `README.md`, actualizar la revisión de Alembic a `b7e24d51c8a9` y enlazar este documento.

---

## 3. Cómo ejecutarlo y comprobarlo

```bash
# 1) Aplicar los 5 cambios de la sección 2 y copiar los archivos nuevos del zip
# 2) Definir ADMIN_API_KEY en el .env
docker compose up --build
```

Al iniciar, el backend ejecuta `alembic upgrade head`: crea la tabla y carga el seed. Si ya tenías la base creada,
no hace falta borrarla (no uses `down -v`): se aplican solo las 2 migraciones nuevas.

**Comprobar la tabla y el seed (criterio 1, RIWI-58 y RIWI-59):**

```bash
docker compose exec backend alembic current
# b7e24d51c8a9 (head)

docker compose exec db psql -U cargaexpress -d cargaexpress \
  -c "SELECT c.carrier_id, c.name, count(*) FROM state_mapping m JOIN carriers c USING (carrier_id) GROUP BY 1,2 ORDER BY 1;"
# SimCarrier Alpha | 9    SimCarrier Beta | 9    SimCarrier Gamma | 9
```

**Comprobar el endpoint y el cambio sin reiniciar (criterios 2 y 3, RIWI-60).** Usa el `carrier_id` de `SimCarrier Gamma` del paso anterior:

```bash
KEY=change_me_admin_key
URL=http://localhost:8000/api/v1/admin/state-mappings
G=<carrier_id de SimCarrier Gamma>

# a) Traducir (llena la caché)
curl -H "X-Admin-Token: $KEY" -G "$URL/resolve" --data-urlencode "carrier_id=$G" --data-urlencode "source_status=En tránsito"
# {"carrier_id":..,"source_status":"En tránsito","canonical_status":"IN_TRANSIT"}

# b) Buscar el mapping_id de ese estado y editarlo
curl -H "X-Admin-Token: $KEY" "$URL?carrier_id=$G"
curl -X PATCH -H "X-Admin-Token: $KEY" -H "Content-Type: application/json" \
  -d '{"canonical_status":"EXCEPTION"}' "$URL/<mapping_id>"

# c) Traducir otra vez, SIN reiniciar nada: ahora devuelve EXCEPTION
curl -H "X-Admin-Token: $KEY" -G "$URL/resolve" --data-urlencode "carrier_id=$G" --data-urlencode "source_status=En tránsito"
```

Para la evidencia en Jira: captura de los pasos (a) y (c), donde el valor cambia sin reiniciar.
También puedes probar desde Swagger (http://localhost:8000/docs) agregando el header `X-Admin-Token`.

**Respuestas del endpoint:** 401 token ausente o incorrecto · 503 `ADMIN_API_KEY` no configurada ·
404 transportadora o mapeo inexistente (o `resolve` sin mapeo) · 409 mapeo duplicado · 422 estado canónico inválido o vacío.

**Estados canónicos válidos:** `CREATED`, `PICKED_UP`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `DELIVERED`,
`DELIVERY_FAILED`, `RETURNED`, `CANCELLED`, `EXCEPTION` (la API acepta minúsculas y las convierte).

**Pruebas automáticas** (las del endpoint necesitan PostgreSQL con migraciones; si no está disponible, se omiten):

```bash
docker compose up -d db
cd backend
export DATABASE_URL=postgresql+asyncpg://cargaexpress:TU_CLAVE@localhost:5432/cargaexpress
uv run alembic upgrade head
uv run pytest -v
```

---

## 4. Cómo funciona la caché (RIWI-60)

1. La primera consulta carga **toda** la tabla en memoria; las siguientes no tocan la base de datos.
2. Al guardar un cambio, el endpoint avisa a la caché **después de confirmar** en la base de datos; la siguiente consulta recarga.
3. Si una lectura estaba en curso justo cuando se invalidó, su resultado no se guarda.
4. **Respaldo por tiempo:** si otro proceso modifica la tabla, esta caché lo nota como máximo a los
   `STATE_MAPPING_CACHE_TTL_SECONDS` (300 s por defecto).

El backend corre con un solo proceso (`Dockerfile`), así que la invalidación es inmediata. Si más adelante se
escala a varios procesos o réplicas, el cambio es inmediato en el que lo recibe y llega a los demás en máximo el TTL;
para hacerlo inmediato en todos habría que agregar una invalidación compartida (Redis o `LISTEN/NOTIFY`).

---

## 5. Supuestos a confirmar con el equipo

1. **Estados canónicos:** la historia cita RN-01 y CA-06, pero ese documento de arquitectura no estaba disponible. La lista de la sección 3 es una propuesta; si el equipo tiene otra, se cambia solo `CANONICAL_STATUSES` (no requiere migración).
2. **Transportadoras simuladas:** `SimCarrier Alpha/Beta/Gamma` con `integration_type = 'simulated'` y `status = 'active'` son nombres propuestos. Si ya existen carriers con esos nombres se reutilizan. Si el equipo define otros, se ajusta el diccionario `SEED` de la migración antes de aplicarla en un entorno compartido.
3. **Clave de administración:** la historia no pide autenticación, pero un endpoint que modifica configuración no debería quedar abierto. Se protege con una clave simple (`ADMIN_API_KEY`); sin ella el endpoint queda deshabilitado (503). La autenticación completa sigue pendiente en la arquitectura del proyecto.
