# Implementation Plan: Publicaciones, selección de cuentas destino y programación

**Branch**: `004-publication-scheduling` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-publication-scheduling/spec.md`

## Summary

Introducir la entidad `Publication` (contenido + cuenta del mismo proyecto), su programación
y la vista Queue, sin publicar nada.

**Backend**:

- Nueva tabla `publications` (migración Alembic `0003`) con:
  - `status` (`unscheduled | scheduled | cancelled`) y `scheduled_at` UTC, coherentes por
    `CHECK`;
  - overrides nullables de título, descripción y hashtags (`NULL` = heredar);
  - un **índice único parcial** `(content_id, account_id) WHERE status != 'cancelled'` que
    garantiza una sola publicación activa por pareja.
- Router `publications.py`:
  - Queue ordenada del proyecto;
  - creación atómica desde un contenido para varias cuentas;
  - consulta;
  - `PATCH` de fecha y overrides;
  - acciones `cancel` y `reactivate`.
- Una función `ensure_can_prepare` concentra las reglas de proyecto activo, cuenta activa y
  archivo disponible para crear, programar y reactivar.

**Frontend**:

- Tercera vista **Queue** en `ProjectDetail`.
- Botón **Prepare publications** en el detalle del contenido, con selector múltiple de
  cuentas y fecha opcional.
- Detalle de publicación con programación, overrides por campo, cancelar y reactivar.

Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**: las existentes (FastAPI, SQLAlchemy 2.x, Alembic, Pydantic;
React + Vite). **Ninguna dependencia nueva.**

**Storage**: SQLite (`AUTOPUBLISHER_DB_PATH`, existente): nueva tabla `publications`. El
almacenamiento multimedia solo se consulta (disponibilidad del archivo); no se escribe.

**Testing**:

- Backend: pytest + `TestClient`, base en `tmp_path`, fechas lejanas (2000 / 2100) para no
  depender del reloj.
- Frontend: Vitest + Testing Library + user-event, con `FakeApi` ampliado.

**Quality tooling**: sin cambios (Ruff, mypy strict; Oxlint, Prettier, `tsc -b`); CI sin
cambios.

**Target Platform**: uso local en Linux/macOS; CI en `ubuntu-latest`

**Project Type**: aplicación web local (frontend + backend separados)

**Performance Goals**: Queue de 200 publicaciones utilizable en < 2 s (SC-008); preparar 3
publicaciones en < 1 min de interacción (SC-002).

**Constraints**:

- Ninguna ejecución ni cambio de estado automático (FR-013).
- Ninguna publicación activa duplicada por pareja contenido + cuenta, garantizado en la base
  (FR-008).
- Creación múltiple atómica (FR-007).
- Sin copiar metadata global (FR-016).
- Sin borrado (FR-022).
- `updated_at` solo con cambios efectivos (FR-021).

**Scale/Scope**:

- 1 tabla nueva y 6 operaciones de API.
- 3 componentes nuevos de interfaz y cambios menores en 3 existentes.

No quedan `NEEDS CLARIFICATION`: los aspectos técnicos que la spec dejó abiertos (mecanismo
de duplicados, formato de fechas, representación de overrides, forma de la API, errores por
cuenta, orden de la Queue) se resuelven en [research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Sin dependencias nuevas. Una tabla con overrides en columnas nullables (sin tabla de metadata ni JSON genérico). Regla de duplicados con un índice parcial nativo de SQLite. Sin capa de servicios, sin máquina de estados, sin router de frontend. "Overdue" es solo visual. No se introduce nada del alcance excluido (scheduler, adaptadores, `PUBLISHING`/`PUBLISHED`/`FAILED`, calendario). | ✅ |
| II. Spec-Driven Development | El plan sigue la spec aprobada, incluida la regla añadida del archivo no disponible (FR-033). Las decisiones que la spec delegó quedan documentadas y no amplían el alcance. | ✅ |
| III. Arquitectura modular | Router `publications.py` separado. Reutiliza `get_project_or_404`, `get_content_or_404`, `MediaStorage.resolve` y `normalize_hashtags` sin duplicarlos. `Publication` es agnóstica de plataforma: la plataforma se obtiene de la cuenta, sin lógica específica de red social, lista para los futuros adaptadores y el scheduler. | ✅ |
| IV. Seguridad (repositorio público) | No se manejan tokens ni credenciales. No se versionan datos: los tests usan `tmp_path`. La API no expone rutas internas (solo `file_url` existente). | ✅ |
| V. Calidad y verificabilidad | Tests para cada punto de SC-009. La duplicidad se prueba también a nivel de índice. Ningún rechazo es silencioso: errores con código estable y detalle por cuenta. Las canceladas permanecen visibles como historial. | ✅ |
| VI. Git y trazabilidad | Rama `004-publication-scheduling`; commits pequeños en inglés; README actualizado (publicaciones, Queue, que programar no publica todavía). | ✅ |
| Arquitectura tecnológica base | SQLite + API REST. Esta feature solo guarda la intención; el "scheduler local dirigido por la base de datos" queda para una feature futura, que podrá consultar `publications` por `status`/`scheduled_at` (índice ya previsto). | ✅ |
| Idioma y convenciones | Código, mensajes de API y UI, README y commits en inglés; artefactos Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS (el diseño de Fase 1 no
añade dependencias ni estructura más allá de lo listado).

## Project Structure

### Documentation (this feature)

```text
specs/004-publication-scheduling/
├── plan.md              # Este archivo
├── research.md          # Fase 0: duplicados, estados, fechas, overrides, API, errores, UI
├── data-model.md        # Fase 1: Publication, estados y transiciones, validaciones
├── quickstart.md        # Fase 1: guía de validación de extremo a extremo
├── contracts/
│   └── api.md           # Fase 1: contrato REST de publicaciones
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
backend/
├── migrations/versions/
│   └── 0003_create_publications.py  # Tabla publications, CHECKs, índice único parcial,
│                                    #   índice de la Queue
├── app/
│   ├── main.py                  # + include_router(publications.router)
│   ├── models.py                # + PublicationStatus (StrEnum), Publication
│   ├── errors.py                # ConflictError: + account_inactive, media_unavailable,
│   │                            #   publication_cancelled, publication_not_cancelled;
│   │                            #   fields opcional (lista)
│   ├── schemas.py               # + PublicationCreate, PublicationUpdate (overrides y
│   │                            #   scheduled_at con zona obligatoria),
│   │                            #   PublicationRead, PublicationContentSummary,
│   │                            #   PublicationAccountSummary
│   ├── contents.py              # file_available reutilizable (sin cambio de comportamiento)
│   └── publications.py          # Router: listar (Queue), crear, consultar, PATCH, cancel,
│                                #   reactivate; ensure_can_prepare; publication_to_read
└── tests/
    ├── conftest.py              # + helpers create_publications, future/past datetimes
    ├── test_publications_create.py  # Una, varias, relación contenido/cuenta/proyecto,
    │                                #   repetidos, otra cuenta de proyecto, inexistente,
    │                                #   inactiva, proyecto inactivo, archivo no disponible,
    │                                #   duplicado activo, atomicidad, fecha pasada/sin zona,
    │                                #   cancelada no bloquea, sin copia de archivo
    ├── test_publications_update.py  # UNSCHEDULED ↔ SCHEDULED, truncado al minuto,
    │                                #   overrides (valor, vacío, null), metadata heredada y
    │                                #   cambio global reflejado, updated_at idempotente,
    │                                #   campos no editables, restricciones por inactivo y
    │                                #   archivo no disponible, cancelada no editable
    ├── test_publications_lifecycle.py  # cancel (idempotente, conserva datos), reactivate
    │                                #   (futura, pasada, sin fecha, conflicto, inactivos,
    │                                #   archivo no disponible, no cancelada), DELETE → 405
    ├── test_publications_queue.py   # Orden por grupos, solo el proyecto, canceladas y
    │                                #   cuentas inactivas visibles, proyecto inactivo,
    │                                #   resúmenes embebidos
    ├── test_persistence.py      # + publicaciones, estados, fechas y overrides tras reiniciar
    └── test_migrations.py       # + 0003 sobre base con datos de 0002; índice parcial

frontend/src/
├── types.ts                     # + PublicationStatus, Publication y resúmenes,
│                                #   PUBLICATION_STATUS_LABELS
├── api.ts                       # + listPublications, createPublications, getPublication,
│                                #   updatePublication, cancelPublication,
│                                #   reactivatePublication
├── utils.ts                     # + toDateTimeLocalValue, fromDateTimeLocalValue, isOverdue
├── test-fake-api.ts             # + publicaciones en memoria con reglas básicas
├── index.css                    # + estilos de Queue y estados
└── components/
    ├── ProjectDetail.tsx        # + vista "Queue"; callback para abrirla desde Content
    ├── ContentLibrary.tsx       # Propaga onOpenQueue
    ├── ContentDetail.tsx        # + botón "Prepare publications" → PublicationCreate
    ├── PublicationCreate.tsx    # Selector múltiple de cuentas, fecha opcional, feedback
    ├── PublicationCreate.test.tsx  # Selección múltiple, cuentas inactivas/ya activas no
    │                            #   seleccionables, fecha, feedback, errores, bloqueos
    ├── PublicationQueue.tsx     # Secciones Scheduled/Unscheduled/Cancelled, estado vacío,
    │                            #   avisos, selección → PublicationDetail
    ├── PublicationQueue.test.tsx   # Orden y grupos, avisos, detalle y edición
    └── PublicationDetail.tsx    # Programación, overrides por campo, cancelar, reactivar

README.md                        # + publicaciones, Queue, programar ≠ publicar
```

**Structure Decision**: se mantienen `backend/` y `frontend/` con el paquete plano `app/`.
Toda la lógica de publicaciones vive en el router `publications.py`, como en las Features
001–003. No se introduce una capa de servicios: las reglas compartidas
(`ensure_can_prepare`, la comprobación de duplicados y `publication_to_read`) son funciones
del propio módulo. El futuro scheduler podrá reutilizarlas.

## Design Notes

- **Modelo**: `Publication` con `Index("uq_publications_active_content_account",
  "content_id", "account_id", unique=True, sqlite_where=text("status != 'cancelled'"))` y
  los `CheckConstraint` de [data-model.md](data-model.md). La migración crea lo mismo con
  `op.create_index(..., sqlite_where=...)`.
- **Creación** (dentro del endpoint, en orden):
  1. `get_content_or_404`;
  2. proyecto activo;
  3. archivo disponible;
  4. el cuerpo ya validado por Pydantic (lista 1–50, `scheduled_at` con zona, truncado y
     futuro);
  5. se cargan en una consulta las cuentas pedidas (sin repetidos) y las publicaciones
     activas del contenido para esas cuentas;
  6. se construye la lista de problemas por cuenta;
  7. si la hay, se lanza un único `ConflictError` o error de validación con `fields`
     (research §6);
  8. si no, se insertan todas y se hace un único `commit`.

  Un `IntegrityError` del índice parcial (carrera) hace rollback y responde
  `409 duplicate`.
- **`scheduled_at`**: un tipo anotado de Pydantic (`AwareDatetime`) rechaza valores sin zona;
  un validador lo trunca al minuto y lo pasa a UTC. La comprobación de "futuro" se hace en el
  endpoint (para la creación, siempre; para el `PATCH`, solo si la fecha cambia), comparando
  con `utc_now()`.
- **`PATCH`**: se rechaza si la publicación está `cancelled`. Se calcula el nuevo estado a
  partir de `scheduled_at` y se aplican solo los campos presentes en `model_fields_set`.
  Si la fecha cambia a un valor no nulo, se llama a `ensure_can_prepare`. `updated_at` solo
  cambia si algo cambia (patrón de `update_content`).
- **Overrides**: tipos anotados propios. Para los textos, un `BeforeValidator` recorta los
  espacios y conserva `""`, sin convertirlo a `None`. Para los hashtags, `normalize_hashtags`
  aplicado solo cuando el valor no es `None`, de modo que `None` siga significando
  "heredar". La columna `hashtags_override` usa `JSON(none_as_null=True)` en el modelo y en
  la migración, para que la herencia sea un SQL `NULL` real y `[]` un override vacío.
- **Reactivar**:
  1. exige `cancelled`;
  2. llama a `ensure_can_prepare`;
  3. comprueba que no haya otra activa para la pareja;
  4. si `scheduled_at` es futura → `scheduled`; si no, `scheduled_at = None` y
     `unscheduled`.

  La respuesta permite a la interfaz detectar que se descartó la fecha comparando con el
  valor anterior.
- **Queue**: `select(Publication, Content, Account)` con joins, `where project_id`, orden
  con `case(...)`, `scheduled_at`, `created_at`/`updated_at` e `id` (contrato). La
  disponibilidad del archivo se calcula una vez por contenido distinto dentro de la misma
  petición.
- **Errores**: `ConflictError` gana un parámetro opcional `fields: list[dict[str, str]]`; el
  manejador lo usa si existe y, si no, mantiene el comportamiento actual con `field`. Los
  errores `422` por cuenta se construyen con `RequestValidationError`, como `_files_error` en
  `contents.py`.
- **UI**:
  - `PublicationCreate` carga `listAccounts` y `listPublications` del proyecto. Solo muestra
    las cuentas activas; las que tienen una publicación activa de ese contenido aparecen
    deshabilitadas con la nota "Already has an active publication".
  - El botón Create se deshabilita sin selección. Envía `scheduled_at` solo si se rellenó la
    fecha.
  - Ante un error muestra `FormError` con la lista de `fields`.
  - Si el proyecto está inactivo, no hay cuentas activas o `file_available` es `false`,
    muestra el motivo en lugar del formulario.
  - `PublicationQueue` recarga desde la API tras cada cambio en el detalle.
  - `PublicationDetail`:
    - deshabilita **Save date** y **Reactivate** con explicación si
      `project_active`/`account.is_active`/`content.file_available` lo impiden;
    - muestra un formulario por campo de metadata con el interruptor "Use content value" /
      "Customize";
    - si la publicación está cancelada, muestra los datos en solo lectura y el botón
      Reactivate.
- **Fechas en la UI**: `toDateTimeLocalValue(iso)` formatea en hora local `YYYY-MM-DDTHH:mm`
  y `fromDateTimeLocalValue(value)` devuelve `new Date(value).toISOString()`. Se muestran con
  `formatDate` (existente, `toLocaleString`). `isOverdue(p)` = `scheduled` y
  `scheduled_at < now`.
- **Tests de persistencia**: misma técnica que las Features 002–003. Se reabre la base con
  `create_app` y se comparan las respuestas de la Queue antes y después.
- **CI**: sin cambios de workflow.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
