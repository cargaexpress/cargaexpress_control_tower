# HU-17 — Simulador de webhooks (Push) para 5 transportadoras Tipo A

**Historia:** Como equipo de datos quiero construir un simulador de webhooks para 5 transportadoras Tipo A, para probar la ingesta de eventos reales.
**Tarea:** RIWI-82 (padre RIWI-81) · **Subtareas:** RIWI-83, RIWI-84, RIWI-85, RIWI-86

Todo lo entregado es **nuevo**: la carpeta `simulator/` y este documento. **No se modificó ningún archivo existente** del repositorio.

## 1. Criterio de aceptación

> "El simulador envía eventos con diferentes formatos, estados variados y eventos duplicados/fuera de orden."

| Parte del criterio | Cómo se cumple | Evidencia |
|---|---|---|
| Diferentes formatos | 5 transportadoras, 5 formatos distintos: JSON plano, JSON anidado, JSON en español, XML y formulario, con distinto Content-Type, nombres de campo y representación de la hora | `formats.py`; `test_formats.py` (ida y vuelta con un decodificador independiente por formato); `test_runner.py::test_los_cinco_formatos_y_estados_variados_llegan` |
| Estados variados | Catálogo de 10–11 estados por transportadora y ciclos de vida con novedad, devolución, pérdida y cancelación | `catalog.py`; `test_generator.py::test_estados_variados_por_transportadora` (se alcanzan todos los estados de cada catálogo) |
| Duplicados | Reenvío idéntico byte a byte (mismo id de evento) con probabilidad y retraso configurables | `chaos.py`; `test_chaos.py`; el receptor de pruebas reporta `repeated_payloads` |
| Fuera de orden | Un evento se intercambia con otro posterior del mismo envío; llega, p. ej., "Entregada" antes de "En reparto" | `chaos.py`; `test_runner.py::test_inyecta_duplicados_identicos_y_desorden_reales` (el desorden se verifica desde lo recibido, no desde el resumen del simulador) |

## 2. Subtareas

| Subtarea | Requisito | Cómo se cumplió | Archivos |
|---|---|---|---|
| **RIWI-83** | Servicio simulador que genera eventos aleatorios por transportadora | Generador por ciclo de vida con pesos, horas crecientes por envío, ids y guías únicos, reproducible con semilla (`SIM_SEED`). El servicio (`python -m webhook_simulator`) genera lotes, los serializa en el formato de cada transportadora y los envía por HTTP POST (push) a `SIM_TARGET_URL_TEMPLATE` | `generator.py`, `formats.py`, `runner.py`, `config.py`, `__main__.py` |
| **RIWI-84** | Catálogo de al menos 6 estados propios por transportadora | Alpha 10, Beta 10, Gamma 10, Delta 11, Epsilon 11, cada uno traducible a los 8 estados canónicos del backend. Pruebas: `test_al_menos_seis_estados_propios_distintos`, cobertura de los 8 canónicos, vocabularios distintos | `catalog.py`, `test_catalog.py` |
| **RIWI-85** | Inyectar duplicados y fuera de orden de forma configurable | `SIM_DUPLICATE_RATE`, `SIM_OUT_OF_ORDER_RATE`, `SIM_DUPLICATE_MAX_DELAY` (0 a 1 y entero ≥ 0, validados) por variable de entorno u opción de línea de comandos. 0 = nada; 1 = siempre | `chaos.py`, `config.py`, `test_chaos.py`, `test_config.py` |
| **RIWI-86** | Dockerizar el simulador por separado del backend | `simulator/Dockerfile` (multietapa: dependencias, pruebas y ejecución; uv 0.11.7 como el backend; usuario sin privilegios; `uv sync --frozen`) y `simulator/docker-compose.yml` propio (servicios `simulator`, `sink`, y `tests` con perfil `test`). Imagen, `pyproject.toml`, `uv.lock` y compose son independientes del backend y no comparten red ni base de datos | `Dockerfile`, `.dockerignore`, `docker-compose.yml` |

## 3. Cómo ejecutarlo

Ver `simulator/README.md`. Resumen:

```bash
cd simulator
docker compose up --build        # simulador + receptor de pruebas en :9000
curl localhost:9000/stats
docker compose run --rm tests    # pruebas
```

## 4. Verificación realizada

- **69 pruebas automáticas pasan** (`pytest`), ejecutadas dentro de una copia del repositorio con `simulator/` añadido. Incluyen una comprobación cruzada de que los estados de Alpha/Beta/Gamma existen en la migración del backend `c4a1209b7e6f`, y una prueba HTTP real contra el receptor de pruebas.
- **Pruebas de mutación:** se rompió a propósito el código en 7 puntos (probabilidad de duplicados, desorden, retraso de duplicados, formato de hora, un estado del catálogo, conteo de éxito HTTP, límite de mensajes). Las pruebas fallaron en las 7.
- **Ejecución real fuera de pytest**, en un entorno limpio solo con dependencias de producción: 300 mensajes a un receptor real (`delivered 300, failed 0`; el receptor contó 33 mensajes idénticos repetidos = 33 duplicados que informó el simulador); formatos XML y formulario verificados en lo recibido; `SIGTERM` termina limpio con resumen y código 0; destino caído → fallos contados y código 1; `--dry-run` imprime sin enviar.
- Un defecto encontrado en la verificación (el resumen contaba el lote completo al detener) se corrigió y quedó cubierto por pruebas.

## 5. Lo que NO se pudo verificar / supuestos

- **Docker no se pudo ejecutar** en el entorno de trabajo. `Dockerfile` y `docker-compose.yml` siguen el patrón del backend y el compose se validó como YAML, pero el `docker compose up --build` real debes probarlo tú. Lo equivalente a la imagen final (entorno limpio con `uv sync --frozen --no-dev` + `python -m webhook_simulator`) sí se ejecutó.
- **El backend no tiene todavía un endpoint de ingesta de webhooks.** Por eso el destino es configurable (`SIM_TARGET_URL_TEMPLATE`) y por defecto apunta al receptor de pruebas incluido. Cuando exista la ingesta, basta cambiar esa variable. El simulador no inventa ni modifica el backend.
- **Delta y Epsilon son transportadoras nuevas**: no existen en la base de datos del backend ni tienen mapeo de estados (la base solo tiene Alpha, Beta y Gamma). No se añadió migración porque no es parte de la historia ni de las subtareas; si se quiere probar la ingesta con ellas habrá que sembrarlas con una migración aparte.
- Observación ajena a HU-17: en el repositorio recibido, `backend/app/main.py` aún no registra el router de HU-15 (`/api/v1/admin/mapeo-estados`); hay que incluirlo cuando se integre esa tarea.
