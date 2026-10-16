# Resumen de cambios — CargaExpress Control Tower

Este documento explica los cambios implementados en las 12 tareas de
endurecimiento y mantenimiento del backend: qué se modificó, con qué propósito
y por qué se tomó cada medida.

## Resumen ejecutivo

Se reforzaron la seguridad multitenant y la validación de configuración,
integridad de datos, respuestas HTTP, documentación OpenAPI, pruebas automatizadas,
CI y guías del proyecto. El objetivo general fue reducir el riesgo de acceso
entre marcas y de datos inconsistentes, y hacer que los problemas de calidad o
deriva del esquema se detecten antes de desplegar.

La revisión Alembic actual es `f6b2a9d14c83`. La suite final ejecutada en Docker
terminó con **91 pruebas aprobadas y 1 advertencia**, con **81.84 % de cobertura**.

## Cambios, propósito y motivo

### 1. Aislamiento de datos por marca

- **Qué se cambió:** se añadió la configuración `BRAND_API_KEYS`, que relaciona
  claves API con IDs de marca. Los endpoints de pedidos y guías obtienen el
  tenant de la clave autenticada, y los servicios filtran las operaciones por
  esa marca. Las operaciones entre marcas se tratan como no encontradas.
- **Propósito:** impedir que una marca consulte o modifique pedidos o guías de
  otra marca.
- **Por qué:** un `X-Brand-Id` enviado por el cliente o un `brand_id` incluido
  en el cuerpo de la petición no son fuentes confiables para autorizar acceso.
  La identidad de la marca debe derivarse de una credencial validada.
- **Pruebas:** se cubrieron la falsificación de `X-Brand-Id`, las consultas y
  modificaciones entre marcas, las guías y el `brand_id` del cuerpo.

### 2. Restricciones de unicidad e índices

- **Qué se cambió:** se creó la migración
  [`f6b2a9d14c83_add_order_and_label_constraints.py`](./backend/alembic/versions/f6b2a9d14c83_add_order_and_label_constraints.py).
  Añade unicidad global para `tracking_number`, unicidad de `brand_order_ref`
  dentro de cada marca y los índices requeridos. La migración comprueba si ya
  hay duplicados y falla con instrucciones antes de crear las restricciones.
  Los duplicados de referencia de pedido se traducen a HTTP 409.
- **Propósito:** preservar la integridad de pedidos y guías en la base de datos.
- **Por qué:** validar solo en la aplicación no evita duplicados en peticiones
  concurrentes. La base de datos debe ser la garantía final. La unicidad global
  de la guía también evita colisiones entre transportistas, según la decisión
  acordada.

### 3. Bloqueo de OpenAPI en producción

- **Qué se cambió:** la ruta personalizada `/docs/api/openapi.json` solo se
  registra fuera de producción. El exportador del contrato sigue usando
  `app.openapi()` directamente.
- **Propósito:** evitar exponer la especificación mediante una ruta alternativa
  en producción.
- **Por qué:** bloquear la documentación estándar no era suficiente si una ruta
  personalizada seguía publicando el esquema.

### 4. Nivel de logging configurable

- **Qué se cambió:** se agregó `LOG_LEVEL`, con validación de valores permitidos,
  y se conectó a la configuración de logging. También se propagó por Compose y
  se documentó en `.env.example`.
- **Propósito:** permitir ajustar el detalle de los registros por entorno.
- **Por qué:** evitar niveles fijados en el código y rechazar configuraciones
  inválidas al iniciar, en lugar de operar con un nivel inesperado.

### 5. Formato uniforme de errores HTTP

- **Qué se cambió:** se registraron handlers para excepciones HTTP de Starlette
  y errores de validación, manteniendo los detalles de campos inválidos en las
  respuestas 422.
- **Propósito:** devolver errores consistentes y útiles a los clientes.
- **Por qué:** los errores del framework y los de validación deben seguir el
  formato de error de la API, sin perder la información necesaria para corregir
  una petición.

### 6. Eliminación de alias heredados y estado canónico compartido

- **Qué se cambió:** se retiraron alias y reexportaciones heredadas que ya no
  tenían usos, y los esquemas relacionados con estados comparten ahora el tipo
  canónico definido en `state_mapping.py`.
- **Propósito:** mantener una sola definición de los estados válidos y reducir
  interfaces redundantes.
- **Por qué:** duplicar definiciones o mantener alias sin consumidores facilita
  divergencias y aumenta el costo de mantenimiento.

### 7. Inclusión de pruebas de simuladores en Docker

- **Qué se cambió:** la imagen de pruebas incluye las pruebas raíz y el
  directorio `simulators/`; se actualizó la documentación sobre la ejecución.
- **Propósito:** hacer que las pruebas del simulador Type C y del seeder WMS
  formen parte del ciclo de validación en Docker.
- **Por qué:** las pruebas que no se copian a la imagen no se ejecutan en ese
  flujo y pueden dejar cambios importantes sin verificar.

### 8. Detección de deriva entre modelos y migraciones

- **Qué se cambió:** el flujo de pruebas ejecuta `alembic check` después de
  aplicar las migraciones.
- **Propósito:** verificar que el esquema declarado por los modelos coincide
  con el esquema migrado.
- **Por qué:** evita que cambios en modelos queden sin una migración
  correspondiente. En la validación final Alembic informó que no había
  operaciones nuevas pendientes.

### 9. Healthcheck de disponibilidad

- **Qué se cambió:** el healthcheck de Docker consulta `/api/v1/ready`.
- **Propósito:** comprobar que la aplicación está lista para atender tráfico.
- **Por qué:** una señal de readiness permite a Docker y a los despliegues
  distinguir una aplicación lista de una que solo está ejecutándose.

### 10. Validación de secretos en producción

- **Qué se cambió:** en producción se validan `API_KEY`, `ADMIN_API_KEY` y las
  claves incluidas en `BRAND_API_KEYS`: deben tener al menos 32 caracteres y
  no comenzar con `change_me`.
- **Propósito:** rechazar secretos débiles o valores de ejemplo antes de iniciar
  la aplicación en producción.
- **Por qué:** los valores de desarrollo no deben aceptarse silenciosamente en
  un entorno expuesto. Se comprobó que la aplicación no lee las credenciales de
  RabbitMQ, por lo que no se añadió una validación ajena a su configuración.

### 11. Herramientas de calidad y CI

- **Qué se cambió:** se incorporaron Ruff, mypy y pytest-cov como herramientas
  de desarrollo; se actualizó `uv.lock`; se añadieron comprobaciones de lint,
  formato, tipos, migraciones y pruebas a CI. El flujo establece un mínimo de
  80 % de cobertura y se agregó una plantilla de pull request.
- **Propósito:** automatizar verificaciones repetibles antes de integrar
  cambios.
- **Por qué:** encontrar errores de estilo, tipos, migraciones o regresiones
  temprano reduce fallas posteriores. Ruff está configurado a 100 caracteres;
  se ignora `E501` para permitir líneas largas existentes de documentación y
  descripciones de API que el formateador no reestructura.
- **Resultado:** Ruff, mypy y la verificación del lockfile pasaron. La cobertura
  final fue de **81.84 %**, por encima del umbral configurado.

### 12. Documentación y contrato OpenAPI

- **Qué se cambió:** se actualizaron el README y `STATE_MAPPING.md` con la
  configuración de claves por marca, `LOG_LEVEL`, los requisitos de secretos
  en producción, las reglas de unicidad, comandos de pruebas y lint, revisión
  Alembic y estructura del proyecto. Se regeneró `docs/api/openapi.json`.
- **Propósito:** documentar el comportamiento actual y mantener el contrato
  publicado alineado con la API.
- **Por qué:** los operadores y desarrolladores necesitan instrucciones
  reproducibles y una especificación que refleje las rutas y esquemas actuales.

## Nota sobre `simulators/type_c/catalogs.py`

En este archivo no cambiaron los catálogos de las tres transportadoras ni sus
flujos de estado. Los cambios fueron de mantenimiento: se modernizaron las
anotaciones `Dict`/`List` a los genéricos integrados de Python, se reformatearon
líneas largas y se añadió encadenamiento de causa al error de conversión del
identificador. El propósito fue alinearlo con el formato y las comprobaciones
estáticas del proyecto, conservando su comportamiento funcional.

## Verificación final

- **Docker / pytest:** 91 aprobadas, 1 advertencia.
- **Cobertura:** 81.84 %.
- **Ruff:** lint y formato aprobados.
- **mypy:** aprobado.
- **Alembic:** `alembic check` sin operaciones nuevas.
- **Lockfile:** verificación de consistencia aprobada.
- **Diff:** `git diff --check` aprobado.
