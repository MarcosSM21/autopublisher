---

description: "Task list for the projects and accounts feature"
---

# Tasks: Gestión básica de proyectos y cuentas

**Input**: Design documents from `specs/002-projects-accounts/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/api.md](contracts/api.md), [quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (SC-007): creación y persistencia de proyectos,
edición, activación/desactivación, varias cuentas por proyecto, asociación cuenta-proyecto,
rechazo de proyectos inexistentes, edición y activación/desactivación de cuentas,
persistencia tras reabrir la base y comportamiento básico de la interfaz. En cada historia
los tests se escriben primero y deben fallar antes de implementar.

**Organization**: tareas agrupadas por historia de usuario. Todo el código, comentarios,
mensajes de API/UI, README y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia de usuario a la que pertenece (US1, US2, US3, US4)

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/`, `backend/tests/`
- Frontend: `frontend/src/`, `frontend/src/components/`
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- Sin capa de servicios ni repositorios: la lógica de cada recurso vive en su router.
- IDs enteros autoincrementales. Sin rutas `DELETE`.
- Las claves de unicidad (`name_key`, `handle_key`) se calculan SIEMPRE con
  `normalize_key()` en Python (NFKC → `casefold()` → NFKC sobre el valor recortado; en
  handles, sin `@` inicial). Nunca `lower()` ni cálculo en SQL.
- `created_at`/`updated_at` los asigna el código (no `onupdate`). En un `PATCH`,
  `updated_at` solo cambia si algún valor normalizado difiere del actual (FR-018); si no hay
  cambio efectivo no se escribe nada y se devuelve `200` con el recurso intacto.
- Errores siempre con el formato de [contracts/api.md](contracts/api.md#error).
- El catálogo de plataformas se duplica explícitamente en backend (`Platform` StrEnum) y
  frontend (`PLATFORMS`), con un comentario en cada lado que apunte al otro.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: añadir las dependencias nuevas.

- [X] T001 Run `uv add sqlalchemy alembic` in `backend/` so that `backend/pyproject.toml` lists both as runtime dependencies and `backend/uv.lock` is updated
- [X] T002 [P] Run `npm install -D @testing-library/user-event` in `frontend/` so that `frontend/package.json` and `frontend/package-lock.json` are updated

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: persistencia, migraciones, normalización, formato de errores, fábrica de la app
y base del cliente HTTP del frontend.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta completar esta fase.

### Backend

- [X] T003 [P] Create `backend/app/config.py` with `BACKEND_DIR = Path(__file__).resolve().parent.parent` and `get_db_path() -> Path` returning `Path(os.environ["AUTOPUBLISHER_DB_PATH"])` when set and non-empty, otherwise `BACKEND_DIR / "data" / "autopublisher.db"` (independent of the working directory)
- [X] T004 [P] Create `backend/app/normalization.py` with: `normalize_key(value: str) -> str` implementing `unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value).casefold())`; `clean_text(value: str | None) -> str | None` that strips outer whitespace and returns `None` for empty results; and `clean_handle(value: str) -> str` that strips outer whitespace, removes ONE leading `@` and strips again. Add a module docstring referencing research.md decision 5
- [X] T005 [P] Create `backend/tests/test_normalization.py` covering: `normalize_key("L4i4") == normalize_key("l4i4")`; `"Straße"` vs `"STRASSE"`; precomposed "é" (written in the test as the escape `\u00e9`) vs decomposed "e" + combining acute accent (escape `e\u0301`); a full-width letter vs its ASCII form; `clean_text("  ")` → `None`; `clean_handle(" @l4i4 ")` → `"l4i4"`; `clean_handle("@@x")` → `"@x"`
- [X] T006 Create `backend/app/db.py` with: `utc_now() -> datetime` (aware UTC); a `UTCDateTime` `TypeDecorator` over `DateTime` that stores naive UTC and returns aware UTC datetimes; `create_db_engine(db_path: Path) -> Engine` for `sqlite:///{db_path}` with `check_same_thread=False` and a `connect` event listener executing `PRAGMA foreign_keys=ON`; `run_migrations(db_path: Path) -> None` that creates the parent directory and runs Alembic `upgrade head` programmatically using `Config(str(BACKEND_DIR / "alembic.ini"))` with `script_location` set to the absolute `BACKEND_DIR / "migrations"` and `sqlalchemy.url` set to the database URL; and a FastAPI dependency `get_session(request: Request) -> Iterator[Session]` that opens a session from the `sessionmaker` stored in `request.app.state.session_factory` and closes it afterwards (depends on T003)
- [X] T007 Create `backend/app/models.py` per [data-model.md](data-model.md): `Base(DeclarativeBase)` whose `MetaData` uses an explicit naming convention (`ix`, `uq`, `fk`, `pk`) for Alembic batch mode; `Platform(StrEnum)` with `youtube, instagram, tiktok, x, threads, telegram` (comment: "Keep in sync with PLATFORMS in frontend/src/types.ts"); `Project` (`projects`: `id`, `name` String(100), `name_key` String unique, `description` String(1000) nullable, `is_active` Boolean default true, `created_at`/`updated_at` `UTCDateTime`); `Account` (`accounts`: `id`, `project_id` FK `projects.id` `ondelete="RESTRICT"`, `platform` String (stores `Platform` values as text, no CHECK constraint), `handle` String(100), `handle_key` String, `display_name` String(100) nullable, `is_active`, `created_at`, `updated_at`) with `UniqueConstraint("project_id", "platform", "handle_key")`. All typed with `Mapped[...]` (depends on T006)
- [X] T008 Initialise Alembic in `backend/`: create `backend/alembic.ini` (`script_location = migrations`, no hard-coded `sqlalchemy.url`), `backend/migrations/script.py.mako` (with type hints on `upgrade() -> None` / `downgrade() -> None`) and `backend/migrations/env.py` using `target_metadata = Base.metadata` from `app.models`, `render_as_batch=True`, and the URL from the Alembic config or, if absent (CLI use), from `app.config.get_db_path()`. Supports online and offline mode. Must pass `ruff check`, `ruff format --check` and `mypy --strict` (depends on T007)
- [X] T009 Create `backend/migrations/versions/0001_create_projects_and_accounts.py` (revision `"0001"`, `down_revision = None`) creating `projects` and `accounts` with every column, the foreign key and the unique constraints exactly as in `app/models.py` (constraint names from the naming convention), plus a `downgrade()` that drops both tables. Generate with `uv run alembic revision --autogenerate` against an empty temporary database if useful, then review and clean it by hand (depends on T008)
- [X] T010 [P] Create `backend/app/errors.py` with: `NotFoundError(message)`; `ConflictError(code: Literal["duplicate", "project_inactive"], message, field: str | None = None)`; a helper building `{"error": {"code", "message", "fields": [{"field", "message"}]}}`; and `register_error_handlers(app)` that maps `NotFoundError` → 404 `not_found`, `ConflictError` → 409, `RequestValidationError` → 422 `validation_error` (one entry per error, `field` = last non-`body` element of `loc`, readable English message, no input echo or internals; length errors MUST state the maximum allowed, e.g. "Must be at most 100 characters."), `StarletteHTTPException` → same format keeping its status code (`404 not_found` for unknown routes, `405 method_not_allowed`), `sqlalchemy.exc.IntegrityError` → after rolling back, 409 `duplicate` ONLY for unique-constraint violations (SQLite message `UNIQUE constraint failed`) and 500 `internal_error` for any other integrity error (e.g. foreign key), and a catch-all `Exception` handler → 500 `internal_error` with the neutral message "An unexpected error occurred. Please try again." (no traces, SQL or paths in the response; the exception is logged server-side without secrets). See [contracts/api.md](contracts/api.md#error)
- [X] T011 Rewrite `backend/app/main.py` as `create_app(db_path: Path | None = None) -> FastAPI`: resolve the path (`db_path` or `get_db_path()`); a lifespan that calls `run_migrations`, creates the engine and stores `sessionmaker(engine, expire_on_commit=False)` in `app.state.session_factory`, and disposes the engine on shutdown; call `register_error_handlers`; keep `GET /health` unchanged; module-level `app = create_app()` so `uv run uvicorn app.main:app --reload` keeps working. Importing the module must not create any file (only the lifespan touches the disk) (depends on T006, T009, T010)
- [X] T012 Create `backend/tests/conftest.py` with fixtures: `db_path` (`tmp_path / "test.db"`), `client` (`with TestClient(create_app(db_path)) as c: yield c`, so the lifespan runs), and helpers `create_project(client, name, description=None) -> dict` and `create_account(client, project_id, platform, handle, display_name=None) -> dict` asserting `201`. Update `backend/tests/test_health.py` to use the `client` fixture; also assert that the unknown-route 404 body has `error.code == "not_found"`, and add a test that registers a temporary route raising `RuntimeError` on an app built with `create_app(db_path)` and asserts a 500 response with `error.code == "internal_error"` and no exception text in the body (use `TestClient(..., raise_server_exceptions=False)`) (depends on T011)
- [X] T013 [P] Create `backend/tests/test_migrations.py`: `run_migrations` on an empty temp file creates `projects` and `accounts`; running it twice is a no-op; `alembic.autogenerate.compare_metadata` between the migrated database and `Base.metadata` returns no differences (schema drift guard); `PRAGMA foreign_keys` returns 1 on engine connections (depends on T011)

### Frontend

- [X] T014 [P] Add `server.proxy` to `frontend/vite.config.ts` forwarding `/api` to `http://127.0.0.1:8000`, keeping the existing Vitest config
- [X] T015 [P] Create `frontend/src/types.ts` with: `type Platform = "youtube" | "instagram" | "tiktok" | "x" | "threads" | "telegram"`; `PLATFORMS: ReadonlyArray<{ value: Platform; label: string }>` in the order YouTube, Instagram, TikTok, X, Threads, Telegram (comment: "Keep in sync with Platform in backend/app/models.py"); `platformLabel(value)`; interfaces `Project` and `Account` matching [contracts/api.md](contracts/api.md) (dates as ISO strings); `FieldError { field: string; message: string }`
- [X] T016 Create `frontend/src/api.ts` with `class ApiError extends Error { status; code; fields: FieldError[] }` and an internal `request<T>(path, init?)` helper that sends/receives JSON under `/api`, returns the parsed body on 2xx, throws `ApiError` from the error format otherwise (including `500 internal_error`, whose server message is shown as is), throws `ApiError` with code `network_error` and message "Could not reach the server." ONLY when `fetch` itself rejects, and throws `ApiError` with code `unexpected_error` and message "The server returned an unexpected response." for non-2xx responses whose body is not in the error format (depends on T015)
- [X] T017 [P] Create `frontend/src/api.test.ts` with `fetch` stubbed via `vi.stubGlobal`: a 2xx JSON response is returned; a 409 error body becomes an `ApiError` with `code`, `message` and `fields`; a 500 `internal_error` body becomes an `ApiError` with that code and message; a non-JSON 502 response becomes `unexpected_error`; a rejected `fetch` becomes `network_error` (depends on T016)
- [X] T018 [P] Create `frontend/src/index.css` with minimal readable styles (two-column layout that stacks on narrow screens, visible "Inactive" badge style, error text style) and import it in `frontend/src/main.tsx`

**Checkpoint**: `uv run pytest` (health, normalización, migraciones) y `npm test` (api) pasan;
el backend arranca, crea la base en `backend/data/` y aplica la migración.

---

## Phase 3: User Story 1 - Crear y consultar proyectos persistentes (Priority: P1) 🎯 MVP

**Goal**: crear proyectos, verlos en una lista con su estado, consultar su detalle y
conservarlos tras reiniciar.

**Independent Test**: crear "L4i4" y "Cybersecurity", verlos en la lista, abrir uno,
reiniciar backend y frontend y comprobar que siguen con los mismos datos
([quickstart.md](quickstart.md) §2–§3 pasos 1, 4 y 5 para proyectos).

### Tests for User Story 1 ⚠️

> Escribir primero y comprobar que fallan.

- [X] T019 [P] [US1] Create `backend/tests/test_projects.py` with tests for: `GET /api/projects` returns `[]` initially; `POST` returns 201 with `id`, trimmed `name`, `description` `null` when omitted or blank, `is_active` true, `created_at == updated_at`, ISO UTC dates; 422 `validation_error` with `field == "name"` for missing, empty, whitespace-only and 101-char names (for the 101-char case the field message mentions the maximum `100`); 422 for a 1001-char description and for unknown body fields; 409 `duplicate` (`field == "name"`) for `"l4i4"` after `"L4i4"` and for `"STRASSE"` after `"Straße"`; list ordered case-insensitively by name and including all projects; `GET /api/projects/{id}` returns the project; 404 `not_found` for an unknown id; `DELETE /api/projects/{id}` returns 405
- [X] T020 [P] [US1] Create `backend/tests/test_persistence.py` with a test that creates two projects through `TestClient(create_app(db_path))`, exits the client (engine disposed), opens a new `TestClient(create_app(db_path))` on the same file and asserts the list is identical (ids, names, descriptions, states, `created_at`, `updated_at`)
- [X] T021 [P] [US1] Rewrite `frontend/src/App.test.tsx` (keep the "AutoPublisher" heading assertion) with `fetch` stubbed and `@testing-library/user-event`: empty state message when the API returns no projects; creating a project calls `POST /api/projects` and the new project appears in the list; selecting a project shows its name, description, status and dates; a 409 `duplicate` response shows the message next to the form and keeps the typed name

### Implementation for User Story 1

- [X] T022 [US1] Create `backend/app/schemas.py` with Pydantic models (`model_config = ConfigDict(extra="forbid")` on inputs, `from_attributes=True` on outputs): `ProjectCreate` (`name` cleaned with `clean_text`, required, 1–100 chars after cleaning; `description` cleaned, ≤ 1000, blank → `None`) and `ProjectRead` (`id`, `name`, `description`, `is_active`, `created_at`, `updated_at`, datetimes serialized as ISO 8601 UTC with `Z`). Error messages in English and user-readable
- [X] T023 [US1] Create `backend/app/projects.py` with `router = APIRouter(prefix="/api/projects")`: `GET ""` lists all projects ordered by `name_key`; `POST ""` (201) checks for an existing `name_key == normalize_key(name)` and raises `ConflictError("duplicate", …, field="name")`, otherwise inserts with `created_at = updated_at = utc_now()`; `GET "/{project_id}"` raises `NotFoundError` when missing. Include the router in `create_app` in `backend/app/main.py` (depends on T022)
- [X] T024 [US1] Add `listProjects()`, `createProject({ name, description })` and `getProject(id)` to `frontend/src/api.ts`
- [X] T025 [P] [US1] Create `frontend/src/components/ProjectForm.tsx`: controlled `name` and `description` fields, props `initialValues`, `submitLabel`, `onSubmit(values) => Promise<void>` and optional `onCancel`; on `ApiError` shows field errors next to each input and other errors above the button, and keeps the typed values; disables submit while saving
- [X] T026 [US1] Create `frontend/src/components/ProjectList.tsx`: renders projects (name + visible "Inactive" badge when `!is_active`), highlights the selected one, calls `onSelect(id)`, shows an empty state ("No projects yet. Create your first project.") and embeds `ProjectForm` for creation (depends on T025)
- [X] T027 [US1] Create `frontend/src/components/ProjectDetail.tsx` showing name, description (or "No description"), Active/Inactive status and created/updated dates via `toLocaleString()`
- [X] T028 [US1] Rewrite `frontend/src/App.tsx`: heading "AutoPublisher"; loads projects on mount; keeps `selectedProjectId` in state; after creating a project reloads the list from the API and selects the new one; renders `ProjectList` and `ProjectDetail`; shows load errors (including `network_error`) in a visible message (depends on T024, T026, T027)

**Checkpoint**: US1 funcional y probada de forma independiente; `uv run pytest` y `npm test`
pasan.

---

## Phase 4: User Story 2 - Añadir y consultar cuentas de un proyecto (Priority: P1)

**Goal**: añadir varias cuentas de distintas plataformas a un proyecto y verlas solo en él,
con persistencia.

**Independent Test**: en "L4i4", añadir Instagram `@l4i4`, TikTok `l4i4` y X `l4i4`;
comprobar que solo aparecen en L4i4 y que siguen asociadas tras reiniciar
([quickstart.md](quickstart.md) §3 pasos 2–5, §4).

### Tests for User Story 2 ⚠️

- [X] T029 [P] [US2] Create `backend/tests/test_accounts.py` with tests for: `POST /api/projects/{id}/accounts` returns 201 with `project_id`, `platform`, `handle` without leading `@` (`"@l4i4"` → `"l4i4"`), `display_name` `null` when blank, `is_active` true, `created_at == updated_at`; several platforms in one project; two YouTube accounts with different handles coexist; 409 `duplicate` (`field == "handle"`) for Instagram `"@L4I4"` after Instagram `"l4i4"` in the same project; the same platform+handle IS allowed in a different project; 422 `validation_error` for missing platform, unknown platform (`"myspace"`), missing/blank/`"@"`-only handle, 101-char handle and 101-char display name (both field messages mention the maximum `100`); 404 `not_found` for a non-existent project AND no account created anywhere; `GET /api/projects/{id}/accounts` returns only that project's accounts ordered by platform then handle (case-insensitive); 404 when listing accounts of an unknown project
- [X] T030 [US2] Extend `backend/tests/test_persistence.py` with a test creating two projects with several accounts each, reopening the app on the same file and asserting every account keeps its `project_id`, data, state and dates
- [X] T031 [P] [US2] Create `frontend/src/components/ProjectDetail.test.tsx` rendering `ProjectDetail` for a selected project with `fetch` stubbed: a selected project lists its accounts with platform label, `@handle`, display name and status; the platform select offers exactly the six platforms; adding an account calls `POST /api/projects/{id}/accounts` and the account appears; a 409 `duplicate` error is shown next to the handle field keeping the typed values

### Implementation for User Story 2

- [X] T032 [US2] Add `AccountCreate` (`platform: Platform`; `handle` cleaned with `clean_handle`, 1–100 chars, required; `display_name` cleaned, ≤ 100, blank → `None`; `extra="forbid"`) and `AccountRead` (`id`, `project_id`, `platform`, `handle`, `display_name`, `is_active`, `created_at`, `updated_at`) to `backend/app/schemas.py`
- [X] T033 [US2] Create `backend/app/accounts.py` with `router = APIRouter(prefix="/api")`: `GET "/projects/{project_id}/accounts"` (404 if the project does not exist; works for inactive projects; ordered by `platform`, `handle_key`); `POST "/projects/{project_id}/accounts"` (201) that raises `NotFoundError` for an unknown project, `ConflictError("project_inactive", "Reactivate the project before adding accounts.")` if the project is inactive, `ConflictError("duplicate", …, field="handle")` if `(project_id, platform, normalize_key(handle))` exists (including inactive accounts), and otherwise inserts with `handle_key = normalize_key(handle)` and both timestamps from `utc_now()`. Include the router in `create_app` in `backend/app/main.py` (depends on T032)
- [X] T034 [US2] Add `listAccounts(projectId)` and `createAccount(projectId, { platform, handle, displayName })` to `frontend/src/api.ts`
- [X] T035 [P] [US2] Create `frontend/src/components/AccountForm.tsx`: platform `<select>` built from `PLATFORMS` (create mode), `handle` and `displayName` inputs, props `initialValues`, `submitLabel`, `onSubmit`, optional `onCancel`, and a `mode: "create" | "edit"` prop (in edit mode the platform is shown read-only); field and general `ApiError` messages shown inline, typed values preserved
- [X] T036 [P] [US2] Create `frontend/src/components/AccountList.tsx`: renders accounts with platform label, `@handle`, display name (if any) and Active/Inactive badge; empty state "No accounts yet."
- [X] T037 [US2] Update `frontend/src/components/ProjectDetail.tsx` to load the project's accounts, render `AccountList` and an `AccountForm` for creation; reload accounts from the API after each successful creation; when the project is inactive, do not render the form and show "Reactivate this project to add accounts." (depends on T034, T035, T036)

**Checkpoint**: US1 y US2 funcionan; el flujo de creación de SC-001 (pasos 1–5) es posible.

---

## Phase 5: User Story 3 - Editar y desactivar/reactivar proyectos (Priority: P2)

**Goal**: editar nombre y descripción de un proyecto y desactivarlo/reactivarlo sin perder
datos ni afectar a sus cuentas.

**Independent Test**: editar un proyecto con cuentas, desactivarlo, comprobar que sigue
visible como inactivo con sus cuentas intactas y reactivarlo ([quickstart.md](quickstart.md)
§3 pasos 6–8, §5).

### Tests for User Story 3 ⚠️

- [X] T038 [P] [US3] Add tests to `backend/tests/test_projects.py` for `PATCH /api/projects/{id}`: changing name and description updates them, changes `updated_at` and keeps `created_at`; sending the same values (including variants with extra outer whitespace that clean to the same stored value) leaves `updated_at` unchanged; changing only the case of its own name is allowed (no self-duplicate) and counts as a change; renaming to another project's name (case/Unicode-insensitive) → 409 `duplicate`; `{"name": ""}`, `{"name": null}`, `{}` and unknown/non-editable fields (`id`, `created_at`) → 422; `{"description": null}` clears it; `{"is_active": false}` deactivates and `{"is_active": true}` reactivates, each changing `updated_at`; repeating `{"is_active": false}` on an inactive project returns 200 and does NOT change `updated_at`; 404 for unknown id
- [X] T039 [P] [US3] Add tests to `backend/tests/test_accounts.py`: deactivating a project leaves all its accounts and their individual `is_active` values unchanged, and they are still listed; `POST` an account to an inactive project → 409 `project_inactive` and nothing is created; after reactivation, adding accounts works again
- [X] T040 [P] [US3] Add UI tests to `frontend/src/App.test.tsx`: editing a project sends `PATCH` and shows the updated values; "Deactivate" marks the project as Inactive in list and detail and hides the account form; "Activate" restores it

### Implementation for User Story 3

- [X] T041 [US3] Add `ProjectUpdate` to `backend/app/schemas.py`: optional `name` (cleaned, 1–100, explicit `null` rejected), optional `description` (cleaned, ≤ 1000, `null`/blank → `None`), optional `is_active: bool`; `extra="forbid"`; a model validator rejecting an empty body; use `model_fields_set` to distinguish omitted fields from explicit `null`
- [X] T042 [US3] Add `PATCH "/{project_id}"` to `backend/app/projects.py`: 404 if missing; for each field in `model_fields_set` compare the cleaned value with the current one; if `name` changes, check `normalize_key` against OTHER projects (409 `duplicate`, `field="name"`) and update `name_key`; if nothing differs return the project without writing; otherwise apply changes, set `updated_at = utc_now()` and commit. Never touch accounts (depends on T041)
- [X] T043 [US3] Add `updateProject(id, patch)` to `frontend/src/api.ts`
- [X] T044 [US3] Update `frontend/src/components/ProjectDetail.tsx` with an "Edit" action that shows `ProjectForm` prefilled (save → `updateProject` → reload), and a "Deactivate"/"Activate" button calling `updateProject(id, { is_active })`; errors shown inline; no delete action. Ensure `frontend/src/App.tsx` reloads the project list after any project change so the list badge stays in sync (depends on T043)

**Checkpoint**: US1–US3 funcionan de forma independiente.

---

## Phase 6: User Story 4 - Editar y desactivar/reactivar cuentas (Priority: P2)

**Goal**: corregir handle o nombre visible de una cuenta y desactivarla/reactivarla sin
eliminarla.

**Independent Test**: editar handle y nombre visible de una cuenta, desactivarla,
comprobar que sigue visible como inactiva en su proyecto y reactivarla con sus datos
intactos.

### Tests for User Story 4 ⚠️

- [X] T045 [P] [US4] Add tests to `backend/tests/test_accounts.py` for `PATCH /api/accounts/{id}`: changing `handle` and `display_name` updates them and `updated_at` while keeping `created_at`, `project_id` and `platform`; `{"handle": "@l4i4"}` on handle `"l4i4"` is not an effective change (`updated_at` unchanged); `{"handle": "L4i4"}` on `"l4i4"` is allowed and counts as a change; a handle matching another account of the same platform in the same project (also when that account is inactive) → 409 `duplicate`; `{"platform": "x"}`, `{"project_id": 2}`, `{}`, `{"handle": ""}`, `{"handle": null}` → 422; `{"display_name": null}` clears it; `{"is_active": false}` / `{"is_active": true}` toggle and change `updated_at`, while repeating the current state returns 200 without changing `updated_at`; editing and toggling accounts of an inactive project works; 404 for unknown id; `DELETE /api/accounts/{id}` → 405
- [X] T046 [P] [US4] Add UI tests to `frontend/src/components/ProjectDetail.test.tsx`: editing an account sends `PATCH /api/accounts/{id}` and shows the new handle with platform read-only; "Deactivate"/"Activate" toggles the account badge; a 409 error is shown inline keeping typed values

### Implementation for User Story 4

- [X] T047 [US4] Add `AccountUpdate` to `backend/app/schemas.py`: optional `handle` (cleaned with `clean_handle`, 1–100, explicit `null` rejected), optional `display_name` (cleaned, ≤ 100, `null`/blank → `None`), optional `is_active: bool`; `extra="forbid"` (so `platform`/`project_id` are rejected); reject empty body
- [X] T048 [US4] Add `PATCH "/accounts/{account_id}"` to `backend/app/accounts.py`: 404 if missing; compare each field in `model_fields_set` with the current value; if `handle` changes, check `(project_id, platform, normalize_key(handle))` against OTHER accounts (409 `duplicate`, `field="handle"`) and update `handle_key`; if nothing differs return without writing; otherwise apply, set `updated_at = utc_now()` and commit. Allowed regardless of the project's state (depends on T047)
- [X] T049 [US4] Add `updateAccount(id, patch)` to `frontend/src/api.ts`
- [X] T050 [US4] Update `frontend/src/components/AccountList.tsx` (and `ProjectDetail.tsx` wiring) with per-account "Edit" (inline `AccountForm` in `mode="edit"`) and "Deactivate"/"Activate" actions calling `updateAccount`, reloading the account list from the API after each success and showing errors inline; no delete action (depends on T049)

**Checkpoint**: las cuatro historias funcionan; SC-001 completo es realizable.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T051 [P] Update `README.md` (English): status (projects and accounts management), local data location `backend/data/autopublisher.db` and that it is git-ignored, `AUTOPUBLISHER_DB_PATH`, migrations applied automatically on startup plus `uv run alembic upgrade head` and how to create a new migration (`uv run alembic revision --autogenerate -m "..."`), and that the frontend dev server proxies `/api` to the backend on port 8000
- [X] T052 [P] Verify repository hygiene: run the backend once with the default path and confirm `git status` does not show `backend/data/` (`git check-ignore backend/data/autopublisher.db`); grep the codebase to confirm there are no `DELETE` routes and no `lower()`-based uniqueness
- [X] T053 Run all quality gates and fix any failure: in `backend/` `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; in `frontend/` `npm test`, `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`
- [X] T054 Execute [quickstart.md](quickstart.md) end to end (§2–§5) with a temporary `AUTOPUBLISHER_DB_PATH`, including the restart in §3 step 4, and record any deviation. Additionally: (a) **SC-006**: on a fresh temporary database, create 20 projects and 100 accounts through the API (e.g. a `curl` loop; 5 accounts per project, varied platforms), then check with `curl -w '%{time_total}'` that `GET /api/projects`, `GET /api/projects/{id}` and `GET /api/projects/{id}/accounts` each answer in < 1 s and that the UI shows the project list and a project detail with no perceptible wait; (b) **SC-003**: with the application running, starting from the main screen, time the manual flow "create a project and add its first account" and confirm it takes less than 1 minute

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; BLOQUEA todas las historias.
  Cadena backend: T003 → T006 → T007 → T008 → T009 → T011 → T012/T013; T004, T005 y T010
  en paralelo. Cadena frontend: T015 → T016 → T017; T014 y T018 en paralelo.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de Foundational y, en la práctica, de US1 (necesita crear y
  seleccionar proyectos: endpoints `POST/GET /api/projects` y `ProjectDetail`).
- **US3 (Phase 5)**: depende de US1; T039 (proyecto inactivo con cuentas) y T040 (el
  formulario de cuenta se oculta en proyectos inactivos, creado en T035/T037) requieren US2.
- **US4 (Phase 6)**: depende de US2.
- **Polish (Phase 7)**: depende de todas las historias.

### User Story Dependencies

```text
Foundational ──▶ US1 ──▶ US2 ──▶ US4
                  │       │
                  └──▶ US3 ◀┘ (solo T039 y T040)
```

### Within Each User Story

- Tests primero (deben fallar) → schemas → routers → cliente API → componentes → integración.
- Las tareas que tocan el mismo archivo (`schemas.py`, `api.ts`, `ProjectDetail.tsx`,
  `test_projects.py`, `test_accounts.py`, `App.test.tsx`, `ProjectDetail.test.tsx`) son
  secuenciales.

### Parallel Opportunities

- T001 ∥ T002.
- Foundational: T003 ∥ T004 ∥ T005 ∥ T010 ∥ T014 ∥ T015 ∥ T018; luego T013 ∥ T017.
- En cada historia, los tests backend y frontend marcados [P] en paralelo, y backend ∥
  frontend (p. ej. T022–T023 ∥ T024–T027).
- US3 y US4 pueden avanzar en paralelo una vez completadas US1 y US2, salvo T039 (US3) y
  T045 (US4), que modifican ambos `backend/tests/test_accounts.py` y deben ejecutarse en
  orden (T039 → T045).

---

## Parallel Example: User Story 1

```bash
# Tests (primero, deben fallar):
Task: "Projects API tests in backend/tests/test_projects.py"            # T019
Task: "Persistence test in backend/tests/test_persistence.py"           # T020
Task: "UI tests in frontend/src/App.test.tsx"                           # T021

# Implementación backend ∥ frontend:
Task: "ProjectCreate/ProjectRead in backend/app/schemas.py"             # T022 → T023
Task: "ProjectForm in frontend/src/components/ProjectForm.tsx"          # T025
Task: "ProjectDetail in frontend/src/components/ProjectDetail.tsx"      # T027
```

## Parallel Example: User Story 2

```bash
Task: "Accounts API tests in backend/tests/test_accounts.py"            # T029
Task: "Account UI tests in frontend/src/components/ProjectDetail.test.tsx" # T031
Task: "AccountForm in frontend/src/components/AccountForm.tsx"          # T035
Task: "AccountList in frontend/src/components/AccountList.tsx"          # T036
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Fase 1 (Setup) y Fase 2 (Foundational).
2. Fase 3 (US1): proyectos persistentes.
3. **STOP y VALIDAR**: tests + quickstart para proyectos.

### Incremental Delivery

1. Setup + Foundational → base lista.
2. US1 → proyectos (MVP).
3. US2 → cuentas: con US1 cubre la creación completa de SC-001.
4. US3 → mantenimiento de proyectos.
5. US4 → mantenimiento de cuentas: SC-001 completo.
6. Polish → README, higiene, quality gates y quickstart.

Commits pequeños en inglés al cerrar cada grupo lógico (p. ej. por fase o por
backend/frontend de cada historia), solo cuando el usuario lo pida o el workflow lo requiera.

---

## Notes

- [P] = archivos distintos, sin dependencias pendientes.
- [Story] mapea cada tarea a su historia para trazabilidad.
- Verificar que los tests fallan antes de implementar.
- Parar en cada checkpoint para validar la historia de forma independiente.
- No ampliar alcance: sin búsqueda, paginación, `DELETE`, router de frontend, capa de
  servicios ni integraciones con plataformas.
