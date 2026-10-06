# Research: Publicaciones, selección de cuentas destino y programación

**Feature**: `004-publication-scheduling` | **Fecha**: 2026-10-06

Decisiones técnicas de la Fase 0. Todas parten del stack ya establecido en las Features
001–003 (FastAPI + SQLAlchemy 2.x + Alembic sobre SQLite; React + Vite) y de la
Constitution (simplicidad, ninguna pérdida o duplicado silencioso de publicaciones). No se
añade ninguna dependencia nueva.

## 1. Regla de "una publicación activa por contenido + cuenta" (FR-008, FR-009)

- **Decision**: índice único **parcial** de SQLite sobre `(content_id, account_id)` con
  `WHERE status != 'cancelled'`, declarado en el modelo (`Index(..., unique=True,
  sqlite_where=...)`) y creado en la migración `0003`. Antes de insertar o reactivar, el
  endpoint consulta las publicaciones activas para devolver un mensaje claro por cuenta; el
  índice es la garantía final ante cualquier carrera (un `IntegrityError` se traduce a
  `409 duplicate`).
- **Rationale**: es la forma más sencilla de que la regla se cumpla a nivel de sistema y no
  solo en la interfaz. Las publicaciones canceladas quedan fuera del índice, así que no
  bloquean nuevas publicaciones (FR-009) y no hay que borrar ni mover nada.
- **Alternatives considered**: comprobación solo en código (vulnerable a dobles clics o
  peticiones concurrentes); columna `active_key` nullable con `UNIQUE` normal (truco
  equivalente pero menos legible); tabla separada de publicaciones activas (sobrediseño).

## 2. Estado y fecha programada (FR-002, FR-003)

- **Decision**: columna `status` (`unscheduled | scheduled | cancelled`) y columna
  `scheduled_at` nullable (`UTCDateTime`, existente). El estado se guarda explícitamente y un
  `CHECK` garantiza la coherencia: `cancelled`, o `scheduled` con fecha, o `unscheduled` sin
  fecha. Los valores en la API y la base usan minúsculas, como el resto de enumeraciones del
  proyecto (`Platform`, `MediaType`); la interfaz muestra `Scheduled`, `Unscheduled` y
  `Cancelled`. `PublicationStatus` es un `StrEnum` con solo esos tres valores.
- **Rationale**: guardar el estado (en lugar de derivarlo) es necesario porque `cancelled` no
  se deduce de la fecha (una cancelada conserva su fecha como historial, FR-019), y permite
  ordenar e indexar la Queue en SQL. El `CHECK` impide estados incoherentes aunque haya un
  error en el código.
- **Alternatives considered**: estado derivado de `scheduled_at` + booleano `is_cancelled`
  (dos fuentes que combinar en cada consulta y orden); máquina de estados con librería
  (innecesario para tres estados).

## 3. Fechas: zona horaria, precisión y validación (FR-011, FR-012)

- **Decision**:
  - La API recibe `scheduled_at` como ISO 8601 **con zona horaria obligatoria** (un valor sin
    offset se rechaza con `422` y el mensaje `Include a time zone.`, añadido a la traducción
    de errores de validación de `app/errors.py`) y lo devuelve en UTC (`...Z`), como las
    demás fechas.
  - El backend trunca segundos y microsegundos (precisión de minuto) y exige que el valor
    resultante sea **estrictamente posterior** al momento actual.
  - La validación de "fecha futura" y de proyecto/cuenta/archivo disponibles solo se aplica
    cuando la fecha **cambia**; reenviar la misma fecha (p. ej. al guardar overrides de una
    publicación vencida) es idempotente.
  - El frontend usa `<input type="datetime-local">` (hora local, precisión de minuto) y
    convierte con `new Date(value).toISOString()`; para mostrar usa `toLocaleString()`.
- **Rationale**: guardar instantes UTC y convertir solo en la interfaz es la forma estándar de
  evitar ambigüedades de zona y de cambio de horario. Exigir offset evita interpretar una hora
  "naive" con la zona equivocada.
- **Alternatives considered**: guardar hora local + nombre de zona IANA (útil para eventos
  recurrentes, innecesario para instantes únicos); aceptar fechas sin offset asumiendo UTC
  (error silencioso de horas).

## 4. Overrides de metadata (FR-014 – FR-017)

- **Decision**: tres columnas nullable en `publications`: `title_override`,
  `description_override` (texto) y `hashtags_override` (JSON). **`NULL` significa "usar
  metadata global"**; cualquier otro valor es un override, incluido el vacío (`""` para
  textos, `[]` para hashtags). El valor efectivo se calcula al serializar
  (`override if override is not None else content.<campo>`).
  - Limpieza de overrides de texto: se recortan los espacios exteriores; un texto vacío o solo
    con espacios se guarda como `""` (override vacío), no como `NULL`.
  - Hashtags: se reutiliza `normalize_hashtags` de la Feature 003. La columna usa
    `JSON(none_as_null=True)` (modelo y migración) para que `None` se guarde como SQL `NULL`
    (heredar) y no como el valor JSON `null`; `[]` se guarda como el JSON `[]` (override
    vacío).
  - Mismos límites que el contenido (200 / 5000 / 30 × 100).
- **Rationale**: no copia valores globales (FR-016), el cambio de la metadata global se ve
  inmediatamente en las publicaciones sin override (FR-015) y distingue "vacío" de "heredar"
  sin columnas booleanas adicionales.
- **Alternatives considered**: booleano + valor por campo (seis columnas para la misma
  información); una columna JSON `overrides` con claves presentes/ausentes (menos tipado y
  más difícil de validar con mypy strict); copiar la metadata al crear (rompe FR-015/FR-016).

## 5. Forma de la API

- **Decision** (detalle en [contracts/api.md](contracts/api.md)):
  - `GET /api/projects/{project_id}/publications`: Queue, ya ordenada.
  - `POST /api/contents/{content_id}/publications`: crea una o varias
    (`{"account_ids": [...], "scheduled_at": ...}`), atómica, `201` con la lista creada.
  - `GET /api/publications/{id}`.
  - `PATCH /api/publications/{id}`: `scheduled_at` y overrides (parcial; `null` quita la
    fecha o el override).
  - `POST /api/publications/{id}/cancel` y `POST /api/publications/{id}/reactivate`.
  - Sin `DELETE` (`405`).
- **Rationale**: sigue el patrón REST existente (colección anidada bajo su padre, recurso por
  id con `PATCH` parcial). Cancelar y reactivar son transiciones con reglas propias
  (conflictos, fechas pasadas), más claras como acciones explícitas que como un
  `PATCH status`.
- **Alternatives considered**: `PATCH {"status": ...}` (mezcla reglas de transición con la
  edición y complica la validación); crear con `POST /api/publications` y `content_id` en el
  cuerpo (menos coherente con `POST /projects/{id}/contents`).

## 6. Errores de la creación múltiple (FR-006, FR-007)

- **Decision**: la creación valida en este orden y se detiene en el primer grupo que falla:
  1. contenido inexistente → `404`;
  2. proyecto inactivo → `409 project_inactive`;
  3. archivo multimedia no disponible → `409 media_unavailable`;
  4. `account_ids` vacío/más de 50 o `scheduled_at` inválido o pasado → `422`;
  5. **validación de todas las cuentas**, recogiendo un problema por cuenta: inexistente o de
     otro proyecto (`422 validation_error`), inactiva (`409 account_inactive`) o con
     publicación activa del contenido (`409 duplicate`).

  Si hay problemas en el paso 5 se devuelve **un único error** cuyo código es el del problema
  más grave presente (`validation_error` > `account_inactive` > `duplicate`) y cuya lista
  `fields` contiene una entrada `account_ids` por cada cuenta problemática con un mensaje que
  la identifica (`"Instagram @l4i4 already has an active publication of this content."`). No
  se crea nada. Una cuenta de otro proyecto o inexistente se trata como dato inválido
  (`422`, no `404`), porque forma parte del cuerpo de una operación atómica que puede
  incluir varias cuentas con problemas distintos; el **mensaje** sí las distingue:
  - inexistente: `"Account {id} not found."`;
  - de otro proyecto: `"Account {id} does not belong to this project."`.
- **Rationale**: reutiliza el formato de error existente (`fields` ya admite varias
  entradas) sin introducir un formato de "resultado por cuenta" como el de importación, que
  aquí no hace falta porque la operación es atómica.
- **Alternatives considered**: resultado parcial por cuenta como en la importación
  (contradice la decisión atómica de la spec); un error por petición sin detalle por cuenta
  (incumple FR-007).

## 7. Nuevos códigos de error

- **Decision**: `ConflictError` admite, además de `duplicate` y `project_inactive`:
  - `account_inactive`: la cuenta debe reactivarse primero;
  - `media_unavailable`: el archivo multimedia del contenido no está disponible (FR-033);
  - `publication_cancelled`: se intenta editar una publicación cancelada (FR-019);
  - `publication_not_cancelled`: se intenta reactivar una publicación que no está cancelada.

  `ConflictError` pasa a aceptar opcionalmente una lista de `fields` para el caso de la
  sección 6. Cancelar una publicación ya cancelada es idempotente (`200`, sin cambios).
- **Rationale**: códigos estables permiten a la interfaz y a los tests distinguir los
  motivos sin analizar mensajes.

## 8. Restricciones por estado del proyecto, la cuenta y el archivo

- **Decision**: una única función `ensure_can_prepare(publication | content, account)` que
  comprueba, para las operaciones que preparan ejecución futura (crear, asignar o cambiar
  fecha, reactivar): proyecto activo → cuenta activa → archivo disponible. Desprogramar,
  cancelar y editar overrides no la llaman.
- **Rationale**: concentra la regla de FR-012, FR-020 y FR-033 en un único punto probado.
  La disponibilidad del archivo reutiliza la comprobación `file_available` existente
  (`storage.resolve(...).is_file()`).

## 9. Queue: consulta y orden (FR-023, FR-024, SC-008)

- **Decision**: una sola consulta con `JOIN` a `contents` y `accounts`, ordenada en SQL con
  `CASE status WHEN 'scheduled' THEN 0 WHEN 'unscheduled' THEN 1 ELSE 2 END`, después
  `scheduled_at` ascendente y finalmente `id` (orden estable). Cada elemento incluye un
  resumen del contenido (`id`, título efectivo para mostrar, `original_filename`,
  `media_type`, `file_url`, `file_available`) y de la cuenta (`id`, `platform`, `handle`,
  `display_name`, `is_active`), para que la interfaz no haga peticiones adicionales. Índice
  `(project_id, status, scheduled_at)`.
  - Las canceladas se ordenan por `updated_at` descendente (las canceladas más recientemente
    primero), lo que resulta más útil como historial que su fecha.
  - Sin paginación ni filtros (spec, Assumptions).
- **Rationale**: 200 publicaciones en una consulta con dos joins y una comprobación de
  archivo por contenido distinto está muy por debajo de los 2 s de SC-008.
- **Alternatives considered**: ordenar en el frontend (duplica la regla y no se prueba en el
  backend); tres endpoints por estado (más peticiones sin beneficio).

## 10. "Vencida" (overdue)

- **Decision**: no se guarda ni se calcula en el backend. La interfaz marca como **Overdue**
  una publicación `scheduled` cuya `scheduled_at` es anterior a la hora actual del
  navegador.
- **Rationale**: es una indicación visual pura (FR-013 prohíbe cambios automáticos de
  estado); backend y navegador comparten reloj en una app local.

## 11. Interfaz

- **Decision**:
  - `ProjectDetail` añade una tercera vista `Queue` al selector `Accounts | Content`.
  - `ContentDetail` gana un botón **Prepare publications** que abre `PublicationCreate`:
    carga cuentas y publicaciones del proyecto, lista las cuentas activas con casillas
    (plataforma, handle, nombre visible), marca como no seleccionables las que ya tienen una
    publicación activa de ese contenido, ofrece un `datetime-local` opcional y muestra tras
    crear "Created N publications for …" con un botón **Open queue**. Si el proyecto está
    inactivo, no hay cuentas activas o el archivo no está disponible, muestra el motivo en
    lugar del formulario.
  - `PublicationQueue`: tres secciones (Scheduled, Unscheduled, Cancelled) con contador y
    estado vacío; cada fila muestra preview pequeña (reutiliza `MediaPreview`), título,
    plataforma, cuenta, estado, fecha local y avisos (Overdue, account inactive, file not
    available). Al seleccionar una fila se abre `PublicationDetail`.
  - `PublicationDetail`: programación (`datetime-local` + Save / Remove date), metadata por
    campo con un interruptor "Use content value" / "Customize" que muestra el valor heredado
    o un campo editable, y acciones Cancel publication / Reactivate. Los botones se
    deshabilitan con explicación cuando el proyecto o la cuenta están inactivos o el archivo
    no está disponible. Tras reactivar con una fecha pasada descartada, muestra un aviso.
  - Toda la navegación se hace con estado de componente, sin router (como hasta ahora).
- **Rationale**: reutiliza los patrones de las Features 002 y 003 (selector de vista,
  detalle bajo la lista, `FieldMessage`/`FormError`, recarga desde la API tras cada cambio).
- **Alternatives considered**: modal (no existe en la UI actual); router para la Queue
  (dependencia y estructura nuevas sin necesidad).

## 12. Tests

- **Decision**:
  - Backend: pytest + `TestClient` como en features anteriores. Las fechas futuras y pasadas
    se fijan lejos del presente (`2100-01-01…` / `2000-01-01…`), así que no hace falta
    simular el reloj, salvo un test de la reactivación con fecha vencida, que inserta la
    fecha pasada directamente en la base (la API no lo permite).
  - El "archivo no disponible" se simula borrando el archivo almacenado en `tmp_path`.
  - Persistencia: reabrir la misma base con `create_app` y comparar las respuestas.
  - Migración: `0003` sobre una base con datos de `0002` sin pérdida, y el índice parcial
    rechaza dos activas pero admite activa + cancelada.
  - Frontend: Vitest + Testing Library con `FakeApi` ampliado (publicaciones en memoria que
    aplica las mismas reglas básicas de duplicados y estados).
- **Rationale**: cubre la lista de SC-009 con las herramientas existentes.
