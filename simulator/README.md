# Simulador de webhooks — 5 transportadoras Tipo A (push)

Servicio **independiente del backend** que envía por HTTP eventos de seguimiento como lo harían
5 transportadoras reales (cada una con su formato y sus propios estados), incluyendo eventos
**duplicados** y **fuera de orden** configurables. Sirve para probar la ingesta de eventos.

| Transportadora | Formato del mensaje | Content-Type | Ejemplo de estados propios |
|---|---|---|---|
| `alpha`   | JSON plano (snake_case, hora ISO UTC)            | `application/json` | `IN_TRANSIT`, `HELD_AT_CUSTOMS`, `RETURNED_TO_SENDER` |
| `beta`    | JSON anidado (camelCase, código numérico, hora en ms) | `application/json` | `100`, `300`, `600`, `999` |
| `gamma`   | JSON en español (hora local -05:00)              | `application/json; charset=utf-8` | `En reparto`, `Intento fallido`, `Novedad` |
| `delta`   | XML (códigos cortos, hora compacta)              | `application/xml` | `PCK`, `HUB`, `NDL`, `RTS` |
| `epsilon` | Formulario (`x-www-form-urlencoded`, hora en segundos) | `application/x-www-form-urlencoded` | `Collected from sender`, `Held - address verification` |

Cada transportadora tiene **10 o 11 estados** (mínimo exigido: 6). Alpha, Beta y Gamma usan exactamente
los estados que ya existen en el mapeo del backend; Delta y Epsilon son nuevas (ver `HU-17_SIMULADOR_WEBHOOKS.md`).

## Ejecutar con Docker (recomendado)

```bash
cd simulator
docker compose up --build              # simulador + receptor de pruebas (sink) en :9000
curl localhost:9000/stats              # ver cuántos mensajes llegaron, y cuántos idénticos repetidos
curl 'localhost:9000/received?carrier=delta&limit=3'
docker compose run --rm tests          # pruebas automáticas (perfil "test")
docker compose down
```

Variables como `SIM_DUPLICATE_RATE=0.5 docker compose up` (o un archivo `.env` junto al compose) cambian el comportamiento.
Para enviar a un backend que corre en tu máquina: `SIM_TARGET_URL_TEMPLATE=http://host.docker.internal:8000/webhooks/{carrier}`.

## Ejecutar sin Docker

```bash
cd simulator
uv sync --python 3.12
uv run python -m webhook_simulator.sink --port 9000 &            # receptor de pruebas
uv run python -m webhook_simulator --max-events 200 --seed 1     # simulador
uv run python -m webhook_simulator --dry-run --max-events 10     # solo muestra, no envía
uv run pytest -q
```

## Configuración (variable de entorno / opción de línea de comandos)

| Variable | Opción | Por defecto | Qué hace |
|---|---|---|---|
| `SIM_TARGET_URL_TEMPLATE` | `--target-url-template` | `http://localhost:9000/webhooks/{carrier}` | Destino; `{carrier}` se reemplaza por el slug |
| `SIM_CARRIERS` | `--carriers` | las 5 | Transportadoras a simular |
| `SIM_RATE` | `--rate` | `5` | Mensajes por segundo (0 = sin pausa) |
| `SIM_SHIPMENTS_PER_BATCH` | `--shipments-per-batch` | `20` | Envíos que se mezclan en cada lote |
| `SIM_MAX_EVENTS` | `--max-events` | `0` | Parar tras N mensajes (0 = indefinido) |
| `SIM_DUPLICATE_RATE` | `--duplicate-rate` | `0.10` | Probabilidad de reenviar un evento idéntico |
| `SIM_OUT_OF_ORDER_RATE` | `--out-of-order-rate` | `0.10` | Probabilidad de que un evento llegue después de uno posterior de su envío |
| `SIM_DUPLICATE_MAX_DELAY` | `--duplicate-max-delay` | `5` | Un duplicado llega como máximo N mensajes después |
| `SIM_SEED` | `--seed` | aleatoria | Repite exactamente la misma simulación |
| `SIM_DRY_RUN` | `--dry-run` / `--no-dry-run` | `false` | Muestra los mensajes (JSON por línea) sin enviarlos |
| `SIM_REQUEST_TIMEOUT` | `--timeout` | `5` | Segundos máximos por envío |

La opción de línea de comandos tiene prioridad sobre la variable de entorno. Al terminar (o con Ctrl+C / `docker stop`)
imprime un resumen: enviados, entregados (2xx), fallidos, únicos, duplicados, fuera de orden. Con `--max-events` y
ninguna entrega correcta termina con código 1.

## Cómo se generan los eventos

1. Cada envío recorre un ciclo de vida (normal, con novedad, devolución, pérdida o cancelación) y en cada paso se elige
   al azar uno de los estados propios de la transportadora. Las horas de un mismo envío siempre son crecientes.
2. Los envíos de un lote se mezclan entre sí.
3. **Fuera de orden:** con probabilidad `out_of_order_rate` un evento se intercambia con otro posterior del mismo envío
   (llega, por ejemplo, "Entregada" antes de "En reparto").
4. **Duplicados:** con probabilidad `duplicate_rate` se reenvía el mismo mensaje, idéntico byte a byte (mismo id), entre 0 y
   `duplicate_max_delay` mensajes después.

## Receptor de pruebas (`webhook_simulator.sink`)

Solo biblioteca estándar. Guarda en memoria lo que llega, sin interpretarlo: `POST /webhooks/<transportadora>`,
`GET /stats`, `GET /received?carrier=&limit=`, `GET /health`. No sustituye a la ingesta del backend.

## Estructura

```
webhook_simulator/  catalog.py (estados) · generator.py (eventos) · formats.py (5 formatos)
                    chaos.py (duplicados/desorden) · runner.py (envío) · config.py · sink.py · __main__.py
tests/              pruebas automáticas · Dockerfile · docker-compose.yml · pyproject.toml / uv.lock
```
