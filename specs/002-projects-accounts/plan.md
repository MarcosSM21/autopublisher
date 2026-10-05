# Implementation Plan: Gestión básica de proyectos y cuentas

**Branch**: `002-projects-accounts` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-projects-accounts/spec.md`

## Summary

Introducir la primera funcionalidad de producto: proyectos y cuentas de redes sociales
asociadas, con persistencia local. El backend FastAPI añade SQLAlchemy 2.x sobre SQLite y
migraciones Alembic que se aplican automáticamente al arrancar, y expone una API REST mínima
bajo `/api` (listar, crear, consultar y editar con `PATCH`, incluida la activación y
desactivación; sin `DELETE`) con validación centralizada en Pydantic y un formato de error
único. El frontend React sustituye la pantalla mínima por una interfaz de dos zonas (lista
de proyectos y detalle con sus cuentas) que se comunica con el backend a través del proxy de
Vite. Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**: FastAPI + Uvicorn, **SQLAlchemy 2.x**, **Alembic** (backend);
React + Vite (frontend)

**Storage**: SQLite local en `backend/data/autopublisher.db` (configurable con
`AUTOPUBLISHER_DB_PATH`); esquema gestionado con migraciones Alembic

**Testing**: pytest + `TestClient` con base temporal por test (backend); Vitest + React
Testing Library + **`@testing-library/user-event`** con `fetch` simulado (frontend)

**Quality tooling**: sin cambios respecto a la Feature 001 (Ruff, mypy strict; Oxlint,
Prettier, `tsc -b`); CI sin cambios

**Target Platform**: desarrollo y uso local en Linux/macOS; CI en `ubuntu-latest`

**Project Type**: aplicación web local (frontend + backend separados)

**Performance Goals**: listas y detalle en < 1 s con 20 proyectos y 100 cuentas (SC-006);
trivial para SQLite en local

**Constraints**: un único usuario, sin autenticación, sin eliminación física, sin
credenciales ni integración con plataformas; `updated_at` solo cambia con modificaciones
efectivas (FR-018)

**Scale/Scope**: 2 tablas, 7 operaciones de API, 1 pantalla con 2 zonas, ~5 componentes

No quedan `NEEDS CLARIFICATION`: todas las decisiones técnicas se resuelven en
[research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Solo 3 dependencias nuevas, cada una con necesidad concreta (ORM, migraciones, interacciones en tests). Sin capa de servicios, repositorios, router de frontend ni gestor de estado. Alcance limitado a la spec: sin `DELETE`, sin integraciones, sin búsqueda ni paginación. | ✅ |
| II. Spec-Driven Development | Plan derivado de la spec aprobada, incluida la aclaración de FR-018. Las decisiones por defecto de la spec (unicidad, inmutabilidad de plataforma, proyecto inactivo) se respetan sin ampliarlas. | ✅ |
| III. Arquitectura modular | Persistencia aislada en `db.py`/`models.py` y `migrations/`; API en routers por recurso; frontend separado que solo conoce el contrato HTTP. Las plataformas son solo un catálogo de valores: no se crea ningún adaptador ni lógica específica de plataforma (llegará con las integraciones). | ✅ |
| IV. Seguridad (repositorio público) | La base de datos vive en `backend/data/`, ya ignorado (`data/`, `*.db`). Sin tokens ni credenciales (FR-027). Errores sin trazas, SQL ni rutas internas (FR-022). | ✅ |
| V. Calidad y verificabilidad | Tests de backend para todos los puntos de SC-007, incluidos persistencia tras reabrir la base y deriva de esquema; tests de UI para los flujos básicos. Mismos comandos y CI que la Feature 001. Ningún fallo silencioso: la UI muestra todos los errores y recarga desde la API tras cada cambio. | ✅ |
| VI. Git y trazabilidad | Rama `002-projects-accounts`; commits pequeños en inglés; README actualizado con la base de datos, la variable de entorno y las migraciones. | ✅ |
| Arquitectura tecnológica base | SQLite local y API REST, como exige la Constitution. Scheduler, multimedia, adaptadores y almacenamiento de secretos no aplican aún. | ✅ |
| Idioma y convenciones | Código, mensajes de la API y de la UI, README y commits en inglés; artefactos de Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS (el diseño de Fase 1 no
añade dependencias, servicios ni estructura más allá de lo listado).

## Project Structure

### Documentation (this feature)

```text
specs/002-projects-accounts/
├── plan.md              # Este archivo
├── research.md          # Fase 0: ORM, migraciones, API, errores, UI, tests
├── data-model.md        # Fase 1: Project, Account, Platform, regla de updated_at
├── quickstart.md        # Fase 1: guía de validación de extremo a extremo
├── contracts/
│   └── api.md           # Fase 1: contrato REST de /api/projects y /api/accounts
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml               # + sqlalchemy, alembic
├── uv.lock
├── alembic.ini                  # script_location = migrations
├── migrations/
│   ├── env.py                   # Usa los metadatos de app.models; render_as_batch=True
│   ├── script.py.mako
│   └── versions/
│       └── 0001_create_projects_and_accounts.py
├── app/
│   ├── __init__.py
│   ├── main.py                  # create_app(db_path): lifespan con migraciones, routers,
│   │                            #   manejadores de error, GET /health; `app = create_app()`
│   ├── config.py                # Resolución de AUTOPUBLISHER_DB_PATH y ruta por defecto
│   ├── normalization.py         # normalize_key (NFKC + casefold + NFKC), clean_text,
│   │                            #   clean_handle; usado por schemas y routers
│   ├── db.py                    # Engine, sesión por petición, PRAGMA foreign_keys,
│   │                            #   UTCDateTime, run_migrations()
│   ├── models.py                # Base, Platform (StrEnum), Project, Account
│   ├── schemas.py               # Esquemas Pydantic de entrada (normalización) y salida
│   ├── errors.py                # NotFoundError, ConflictError y manejadores → formato único
│   ├── projects.py              # Router /api/projects
│   └── accounts.py              # Router /api/projects/{id}/accounts y /api/accounts/{id}
└── tests/
    ├── conftest.py              # Fixtures: base temporal, cliente, helpers de creación
    ├── test_health.py           # Sin cambios de comportamiento (usa el fixture client)
    ├── test_normalization.py    # Equivalencias Unicode de normalize_key y limpieza
    ├── test_projects.py         # Crear, listar, consultar, editar, activar/desactivar,
    │                            #   duplicados, validaciones, updated_at idempotente
    ├── test_accounts.py         # Varias cuentas, asociación, proyecto inexistente/inactivo,
    │                            #   normalización de handle, edición, activar/desactivar
    ├── test_persistence.py      # Reabrir la misma base con una nueva app
    └── test_migrations.py       # upgrade head sobre base vacía + deriva de esquema

frontend/
├── package.json                 # + @testing-library/user-event (dev)
├── vite.config.ts               # + server.proxy '/api' → http://127.0.0.1:8000
└── src/
    ├── main.tsx                 # + import del CSS
    ├── index.css                # Estilos mínimos
    ├── types.ts                 # Project, Account, Platform, PLATFORM_LABELS
    ├── api.ts                   # Funciones tipadas sobre fetch + ApiError
    ├── api.test.ts              # Traducción de respuestas de error a ApiError
    ├── App.tsx                  # Layout: lista de proyectos + detalle del seleccionado
    ├── App.test.tsx             # Flujos de proyectos en la UI con fetch simulado
    └── components/
        ├── ProjectList.tsx      # Lista con estado activo/inactivo + formulario de creación
        ├── ProjectForm.tsx      # Crear/editar proyecto (errores por campo)
        ├── ProjectDetail.tsx    # Datos, editar, activar/desactivar, cuentas
        ├── ProjectDetail.test.tsx # Flujos de cuentas en la UI con fetch simulado
        ├── AccountList.tsx      # Cuentas con estado, editar, activar/desactivar
        └── AccountForm.tsx      # Crear/editar cuenta (plataforma solo al crear)

README.md                        # + datos locales, AUTOPUBLISHER_DB_PATH, migraciones, proxy
```

**Structure Decision**: se mantienen `backend/` y `frontend/` de la Feature 001. El backend
sigue siendo un paquete plano `app/` con un módulo por responsabilidad; la lógica de cada
recurso vive en su router porque es CRUD sencillo, y una capa de servicios o repositorios
sería una abstracción prematura (Constitution I). Las migraciones quedan fuera de `app/`
(convención de Alembic). En el frontend se introduce `components/` porque ya hay varias
piezas de UI con responsabilidad propia; `api.ts` aísla la comunicación HTTP.

## Design Notes

- **Arranque y migraciones**: `create_app(db_path=None)` resuelve la ruta (argumento →
  `AUTOPUBLISHER_DB_PATH` → valor por defecto), crea el directorio y, en el lifespan,
  ejecuta `alembic upgrade head` de forma programática antes de aceptar peticiones. El
  comando documentado `uv run uvicorn app.main:app --reload` no cambia.
- **Sesiones**: una sesión SQLAlchemy por petición mediante dependencia de FastAPI; commit
  explícito en las operaciones de escritura.
- **Regla FR-018**: los `PATCH` comparan cada valor normalizado con el actual; solo si hay
  diferencias se escriben los cambios y se asigna `updated_at`. No se usa `onupdate`.
  Detalle en [data-model.md](data-model.md#regla-de-updated_at-fr-018).
- **Duplicados**: las columnas `name_key` y `handle_key` se calculan en Python con
  `normalize_key` (NFKC + `casefold()` + NFKC, sobre el valor recortado), nunca con
  `lower()`, y tienen índices únicos
  ([research.md](research.md), decisión 5). La comprobación excluye el propio registro en
  las ediciones; el índice
  único es la garantía final: un `IntegrityError` por violación de unicidad se traduce a
  `409 duplicate`; cualquier otra violación de integridad, a `500 internal_error`.
- **Errores**: contrato en [contracts/api.md](contracts/api.md#error). Mensajes en inglés
  pensados para mostrarse directamente en la UI.
- **UI**:
  - La lista muestra todos los proyectos con una marca visible "Inactive".
  - Al seleccionar uno se cargan su detalle y sus cuentas.
  - Los formularios conservan lo escrito y muestran los errores por campo devueltos por la
    API.
  - El formulario de cuenta no se ofrece (o se deshabilita con explicación) si el proyecto
    está inactivo.
  - No hay botones de eliminar.
- **Tests de persistencia**: se crea una app sobre un fichero temporal, se insertan datos,
  se cierra (se libera el engine), se crea otra app sobre el mismo fichero y se verifican
  datos, estados, fechas y asociaciones (FR-019, SC-002).
- **CI**: sin cambios; los nuevos tests se ejecutan con los comandos existentes. Los tests
  no dependen de `backend/data/`.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
