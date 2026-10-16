# HU-12 — Mapeo configurable de estados

La tabla `state_mapping` traduce el estado recibido de cada transportadora
(`raw_status`) a un estado canónico. La asignación se guarda en PostgreSQL y se
puede modificar mediante la API admin sin reiniciar el servicio.

## Estados canónicos (RN-01)

La API y la base de datos aceptan exactamente estos ocho valores:

`CREATED`, `PICKED_UP`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `EXCEPTION`,
`DELIVERED`, `RETURNED` y `LOST_OR_DAMAGED`.

Los eventos sin traducción no se convierten automáticamente a otro estado: la
resolución devuelve `404`. `DELIVERED`, `RETURNED` y `LOST_OR_DAMAGED` son
terminales para las reglas posteriores de órdenes; esa transición de orden no
se implementa en este modelo.

## Modelo, datos iniciales y migraciones

`StateMapping` tiene `id`, `carrier_id`, `raw_status`, `canonical_status`,
`created_at` y `updated_at`. La clave foránea apunta a `carriers.carrier_id`;
una restricción única impide más de una traducción para el par
`(carrier_id, raw_status)`, y una restricción `CHECK` limita el estado canónico
en la propia base de datos.

La revisión `a3f1c9d27b45` creó la tabla; `b7e24d51c8a9` agregó las
transportadoras simuladas. La revisión `c4a1209b7e6f` alinea los nombres de
columnas con el contrato `id` / `raw_status`, transforma estados anteriores que
ya no pertenecen al catálogo a `EXCEPTION`, agrega los mapeos de pérdida/daño y
aplica la restricción de catálogo. Cada transportadora simulada tiene al menos
seis estados de origen distintos. En instalaciones existentes, esta migración
actualiza los datos; no borra ni reemplaza los mapeos válidos ya personalizados.

La revisión actual es `f6b2a9d14c83 (head)`. Agrega unicidad global a
`shipping_labels.tracking_number`, unicidad por marca a
`(orders.brand_id, orders.brand_order_ref)` e índices para
`orders.brand_id`, `orders.status`, `shipping_labels.order_id` y
`shipping_labels.carrier_id`. La migración detecta duplicados existentes y
detiene la actualización con instrucciones para deduplicar antes de reintentar.

Las migraciones se ejecutan automáticamente al iniciar el servicio backend.
También se pueden comprobar con:

```powershell
docker compose exec backend alembic current
```

La revisión esperada es `f6b2a9d14c83 (head)`.

## API administrativa y caché

Los endpoints están en `/api/v1/admin/state-mappings` y requieren el header
`X-Admin-Token`. Configura `ADMIN_API_KEY` en `.env`; si está vacío, la API admin
queda deshabilitada y responde `503`.

Las rutas de pedidos y guías obtienen el `brand_id` de la clave enviada en
`X-API-Key`, mediante el objeto JSON `BRAND_API_KEYS` (`clave: brand_id`).
`X-Brand-Id` no determina el tenant. `API_KEY` configura la clave compartida y
`LOG_LEVEL` admite `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL` (por defecto
`INFO`). En producción, `API_KEY`, `ADMIN_API_KEY` y cada clave de marca deben
tener al menos 32 caracteres y no empezar con `change_me`.

- `GET /api/v1/admin/state-mappings?carrier_id=...`: lista mapeos.
- `GET /api/v1/admin/state-mappings/resolve?carrier_id=...&raw_status=...`:
  resuelve un estado recibido.
- `POST /api/v1/admin/state-mappings`: crea un mapeo.
- `PATCH /api/v1/admin/state-mappings/{id}`: modifica un mapeo.
- `DELETE /api/v1/admin/state-mappings/{id}`: elimina un mapeo.

La caché en `backend/app/services/state_mapping_cache.py` carga los mapeos bajo
demanda y los conserva en memoria durante
`STATE_MAPPING_CACHE_TTL_SECONDS` (300 por defecto). Crear, editar o eliminar
invalida la caché después de confirmar la transacción; por eso el siguiente
resolve en ese proceso lee el valor actualizado sin reinicio. El TTL también
permite detectar cambios hechos directamente en la base de datos o en otra
réplica. En varios procesos, la propagación puede tardar hasta el TTL.

## Ejecutar pruebas en Docker

Desde la raíz del repositorio, configura las credenciales de PostgreSQL en
`.env` y ejecuta:

```powershell
docker compose --profile test up --build --abort-on-container-exit --exit-code-from test test
```

El servicio de pruebas espera a PostgreSQL, aplica las migraciones y ejecuta
`alembic check` y las pruebas de `backend/tests/` y `tests/`, incluidos los
simuladores; no hace falta un entorno `.venv` local.

Para lint, formato y tipado local, desde `backend`:

```powershell
uv sync --frozen
uv run ruff check --config pyproject.toml app tests ../simulators ../tests ../scripts
uv run ruff format --config pyproject.toml --check app tests ../simulators ../tests ../scripts
uv run mypy app
```

Configura `DATABASE_URL` y `TEST_DATABASE_URL` para una base PostgreSQL aislada
antes de correr las pruebas localmente:

```powershell
uv run alembic upgrade head
uv run alembic check
uv run pytest -v --cov=app --cov-report=term-missing --cov-fail-under=80 tests ../tests
```
