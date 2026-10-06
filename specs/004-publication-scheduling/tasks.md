---

description: "Task list for the publications, target account selection and scheduling feature"
---

# Tasks: Publicaciones, selección de cuentas destino y programación

**Input**: Design documents from `specs/004-publication-scheduling/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/api.md](contracts/api.md), [quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (SC-009):

- creación de una publicación y para múltiples cuentas;
- relación correcta contenido/cuenta/proyecto;
- rechazo de cuenta de otro proyecto, de cuenta inactiva y en proyecto inactivo;
- prevención de duplicados activos;
- cancelación y reactivación;
- `UNSCHEDULED` ↔ `SCHEDULED`;
- persistencia tras reinicio;
- metadata heredada, overrides y cambio global reflejado sin override;
- Queue;
- selección múltiple de cuentas en el frontend.

En cada historia los tests se escriben primero y deben fallar antes de implementar.

**Organization**: tareas agrupadas por historia de usuario. Todo el código, comentarios,
mensajes de API/UI, README y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia de usuario a la que pertenece (US1–US6)

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`
- Frontend: `frontend/src/`, `frontend/src/components/`
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- Sin capa de servicios: toda la lógica vive en el router `backend/app/publications.py`,
  reutilizando `get_project_or_404` (`app.projects`), `get_content_or_404` y la comprobación
  de disponibilidad del archivo (`app.contents`) y `normalize_hashtags` (`app.schemas`). Sin
  ruta `DELETE`.
- **Estados**: solo `PublicationStatus` = `unscheduled`, `scheduled`, `cancelled` (minúsculas
  en base y API). Nunca `draft`, `publishing`, `published` ni `failed`. Invariante:
  `cancelled`, o `scheduled` con `scheduled_at`, o `unscheduled` sin `scheduled_at`.
- **Nada se ejecuta por el paso del tiempo**: ningún código cambia el estado de una
  publicación salvo una petición explícita del usuario.
- **Fechas**: la API exige ISO 8601 con zona (`AwareDatetime`), trunca a minuto y guarda UTC
  (`UTCDateTime`). "Futura" = estrictamente posterior a `utc_now()`.
- **Overrides**: `NULL` = heredar del contenido; `""`/`[]` = override vacío. Nunca se copian
  los valores globales en la publicación. La metadata efectiva se calcula al serializar.
- **`ensure_can_prepare`** (proyecto activo → cuenta activa → archivo disponible) se llama
  solo en crear, asignar/cambiar fecha (si cambia) y reactivar. Desprogramar, editar
  overrides y cancelar nunca la llaman.
- `created_at`/`updated_at` los asigna el código; `updated_at` solo cambia con cambios
  efectivos (FR-021).
- Errores con el formato existente ([contracts/api.md](contracts/api.md)); mensajes en inglés
  sin rutas internas.
- El catálogo `PublicationStatus` se duplica en backend (`StrEnum`) y frontend (`types.ts`),
  con un comentario en cada lado que apunte al otro.
- En los tests de backend, fechas futuras en 2100 y pasadas en 2000 (no se simula el reloj).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: no hay dependencias nuevas ni cambios de configuración.

- [X] T001 Verify the baseline on branch `004-publication-scheduling`: run `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`; all must pass before any change (record any pre-existing failure instead of fixing it silently)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: modelo, migración, errores, esquemas, router base, reglas compartidas,
fixtures de test y tipos/cliente del frontend.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta completar esta fase.

### Backend

- [X] T002 [P] Add to `backend/app/models.py`:
  - `PublicationStatus(StrEnum)`: `UNSCHEDULED = "unscheduled"`, `SCHEDULED = "scheduled"`,
    `CANCELLED = "cancelled"`. Comment: keep in sync with `frontend/src/types.ts`.
  - Model `Publication` (`__tablename__ = "publications"`) with the columns of
    [data-model.md](data-model.md):
    - `project_id`, `content_id`, `account_id`: FKs to `projects.id`, `contents.id`,
      `accounts.id`, all `ondelete="RESTRICT"`;
    - `status`: `String(20)`;
    - `scheduled_at`: `UTCDateTime`, nullable;
    - `title_override`: `String(200)`, nullable; `description_override`: `String(5000)`,
      nullable; `hashtags_override`: `Mapped[list[str] | None]` with
      `JSON(none_as_null=True)`, nullable (Python `None` must be stored as SQL `NULL` =
      inherit, `[]` as the JSON array `[]` = explicit empty override);
    - `created_at`, `updated_at`: `UTCDateTime`.
  - `__table_args__`:
    - `CheckConstraint("status IN ('unscheduled', 'scheduled', 'cancelled')", name="status_valid")`;
    - `CheckConstraint("status = 'cancelled' OR (status = 'scheduled' AND scheduled_at IS NOT NULL) OR (status = 'unscheduled' AND scheduled_at IS NULL)", name="status_matches_schedule")`;
    - `Index("uq_publications_active_content_account", "content_id", "account_id", unique=True, sqlite_where=text("status != 'cancelled'"))`;
    - `Index("ix_publications_project_id_status_scheduled_at", "project_id", "status", "scheduled_at")`.
  - Add `"ck": "ck_%(table_name)s_%(constraint_name)s"` to `NAMING_CONVENTION` only if it
    does not alter existing tables' constraint names (they have no CHECKs, so it is safe).
- [X] T003 Create `backend/migrations/versions/0003_create_publications.py`:
  - `revision = "0003"`, `down_revision = "0002"`;
  - creates `publications` exactly matching the model (same constraint and index names,
    `op.create_index(..., unique=True, sqlite_where=sa.text("status != 'cancelled'"))` for
    the partial index, and `sa.JSON(none_as_null=True)` for `hashtags_override`), with the
    same "stored as naive UTC" comment as `0002`. CHECK constraint names must be identical
    in model and migration (e.g. `ck_publications_status_valid`,
    `ck_publications_status_matches_schedule`);
  - `downgrade` drops both indexes and the table.

  Run the existing schema-drift test (`test_migrations_match_models`); if Alembic reports a
  spurious diff only because of the partial index's `sqlite_where`, keep the index and make
  the comparison ignore that single dialect detail with the smallest possible change in
  `backend/tests/test_migrations.py`, documented in a comment. Depends on T002.
- [X] T004 [P] Extend `backend/app/errors.py`:
  - `ConflictError.code` literal adds `account_inactive`, `media_unavailable`,
    `publication_cancelled`, `publication_not_cancelled`;
  - `ConflictError.__init__` accepts an optional keyword `fields: list[dict[str, str]] | None`;
    `_handle_conflict` uses `exc.fields` when given, otherwise keeps the current
    `field`-based behaviour;
  - in `_validation_message`, map the Pydantic error type `timezone_aware` to the message
    "Include a time zone." (so a `scheduled_at` without offset is reported with that text
    on the `scheduled_at` field);
  - add a helper `field_errors(entries: list[tuple[str, str]]) -> RequestValidationError`
    that produces a `422 validation_error` with one `fields` entry per `(field, message)`
    and a general message "The request contains invalid data." (generalise the
    `_files_error` pattern of `backend/app/contents.py`; keep `_files_error` working).
- [X] T005 [P] Add to `backend/app/schemas.py`:
  - `ScheduledAt` annotated type: `AwareDatetime` (rejects values without a time zone; the
    message "Include a time zone." comes from the mapping added in T004), converted to UTC and truncated to
    the minute (`replace(second=0, microsecond=0)`) in an `AfterValidator`.
  - `TitleOverride` / `DescriptionOverride`: `str | None`; a `BeforeValidator` strips outer
    whitespace **keeping `""`** (do not reuse `_clean_optional`, which turns it into
    `None`); `max_length` 200 / 5000.
  - `HashtagsOverride`: `list[str] | None`, normalized with `normalize_hashtags` only when
    not `None`.
  - `PublicationCreate(InputModel)`: `account_ids: list[int]` (1–50 items, `min_length=1`,
    `max_length=50`), `scheduled_at: ScheduledAt | None = None`.
  - `PublicationUpdate(UpdateModel)`: `scheduled_at: ScheduledAt | None = None`,
    `title_override`, `description_override`, `hashtags_override` (all default `None`; the
    endpoint distinguishes "omitted" from `null` via `model_fields_set`).
  - `PublicationContentSummary` (`id`, `title`, `original_filename`, `media_type:
    MediaType`, `file_url`, `file_available`), `PublicationAccountSummary` (`id`,
    `platform: Platform`, `handle`, `display_name`, `is_active`) and `PublicationRead`
    with every field of [contracts/api.md](contracts/api.md#publication) (`status:
    PublicationStatus`, raw overrides, effective `title`/`description`/`hashtags`,
    `content`, `account`, `project_active`, `created_at`, `updated_at`).
- [X] T006 Create `backend/app/publications.py` and register it in `backend/app/main.py`
  (`app.include_router(publications.router)`):
  - `router = APIRouter(prefix="/api", tags=["publications"])`, `SessionDep`, and
    `StorageDep` reused from `app.contents`;
  - in `backend/app/contents.py`, rename `_file_available` to a public
    `file_available(storage, content) -> bool` (update its call site; no behaviour change);
  - `get_publication_or_404(session, publication_id)` → `NotFoundError("Publication not found.")`;
  - `publication_to_read(publication, content, account, project, storage,
    file_available: bool | None = None) -> PublicationRead`: computes the effective metadata
    (`override if override is not None else content.<field>`), the summaries and
    `project_active`; accepts a precomputed `file_available` so the Queue can cache it per
    content;
  - `ensure_can_prepare(project, account, content, storage)`: raises, in this order,
    `ConflictError("project_inactive", "Reactivate the project before scheduling publications.")`,
    `ConflictError("account_inactive", "Reactivate the account before scheduling publications.")`,
    `ConflictError("media_unavailable", "The media file of this content is not available.")`;
  - `ensure_future(value: datetime, field="scheduled_at")`: raises `field_errors` with
    "Choose a date and time in the future." when `value <= utc_now()`;
  - `find_active(session, content_id, account_ids, exclude_id=None) -> list[Publication]`:
    active (`status != cancelled`) publications of the content for those accounts.

  Depends on T002, T004, T005.
- [X] T007 Extend `backend/tests/conftest.py` with helpers:
  - `FUTURE = "2100-01-01T10:00:00Z"`, `LATER = "2100-02-01T18:30:00Z"`,
    `PAST = "2000-01-01T10:00:00Z"`;
  - `setup_project(client, platforms=("instagram", "tiktok", "x")) -> tuple[project,
    content, list[account]]`: creates a project, imports one image (`make_image`) and one
    account per platform;
  - `create_publications(client, content_id, account_ids, scheduled_at=None) -> list[dict]`
    asserting `201`;
  - `stored_file(media_dir, db_path, content_id) -> Path`: locates the stored file of a
    content via its `storage_path` row (to delete it in "file not available" tests).

  Depends on T006.
- [X] T008 Update `backend/tests/test_migrations.py`:
  - table-creation test also expects `publications`; idempotency test expects version
    `"0003"`;
  - new test: upgrade to `0002`, insert a project, an account and a content row, upgrade to
    `head`, assert the rows survive and `publications` exists;
  - new test on the partial index (raw SQL after `run_migrations`): two rows with the same
    `(content_id, account_id)` and `status = 'unscheduled'` → `IntegrityError`; one
    `cancelled` + one `unscheduled` → allowed; two `cancelled` → allowed;
  - new test: the `CHECK` rejects `status = 'scheduled'` with `scheduled_at` NULL and
    `status = 'draft'`;
  - new test: inserting a `Publication` through the ORM with `hashtags_override=None` stores
    SQL `NULL` (`SELECT hashtags_override IS NULL` is true) and with `[]` stores the JSON
    `'[]'` (`IS NULL` is false), and both read back as `None` and `[]`.

  Depends on T003.

### Frontend

- [X] T009 [P] Extend `frontend/src/types.ts`:
  - `PublicationStatus = "unscheduled" | "scheduled" | "cancelled"` (comment: keep in sync
    with `backend/app/models.py`) and `PUBLICATION_STATUS_LABELS` (`Unscheduled`,
    `Scheduled`, `Cancelled`);
  - interfaces `PublicationContentSummary`, `PublicationAccountSummary` and `Publication`
    matching [contracts/api.md](contracts/api.md#publication).
- [X] T010 [P] Add to `frontend/src/api.ts`: `listPublications(projectId)`,
  `createPublications(contentId, { account_ids, scheduled_at? })`, `getPublication(id)`,
  `updatePublication(id, changes: PublicationUpdate)` (with `PublicationUpdate =
  Partial<{ scheduled_at: string | null; title_override: string | null;
  description_override: string | null; hashtags_override: string[] | null }>`),
  `cancelPublication(id)` and `reactivatePublication(id)` (both `POST` without body).
- [X] T011 [P] Extend `frontend/src/utils.ts` with:
  - `toDateTimeLocalValue(iso: string): string` → local `YYYY-MM-DDTHH:mm`;
  - `fromDateTimeLocalValue(value: string): string` → `new Date(value).toISOString()`;
  - `isOverdue(publication, now = new Date()): boolean` → `status === "scheduled"` and
    `scheduled_at` earlier than `now`.

  Add cases to `frontend/src/utils.test.ts` (round trip local value ↔ ISO keeps the same
  instant; overdue true/false; not overdue when unscheduled or cancelled).
- [X] T012 Extend `FakeApi` in `frontend/src/test-fake-api.ts` with a `publications:
  Publication[]` store, `addPublication(values)` and routes that apply the basic rules:
  - `GET /projects/{id}/publications` (contract order: scheduled by date, unscheduled,
    cancelled);
  - `POST /contents/{id}/publications`: `404` unknown content, `409 project_inactive`,
    `409 media_unavailable` when `file_available` is false, `409 account_inactive`,
    `409 duplicate` with one `fields` entry per conflicting account (no partial creation);
    otherwise creates one `unscheduled`/`scheduled` publication per account with effective
    metadata copied from the content at read time;
  - `GET /publications/{id}`, `PATCH /publications/{id}` (scheduled_at → status, overrides
    `null` = inherit, `409 publication_cancelled`), `POST …/cancel`,
    `POST …/reactivate` (future date → scheduled, otherwise unscheduled with
    `scheduled_at: null`; `409 duplicate` if another active exists);
  - effective `title`/`description`/`hashtags` recomputed from the current content on every
    read, so content edits are reflected.

  Depends on T009.

**Checkpoint**: `uv run pytest`, `uv run mypy .`, `npm test` and `npm run typecheck` pass;
the app starts and applies migration `0003`.

---

## Phase 3: User Story 1 - Preparar publicaciones de un contenido en varias cuentas (Priority: P1) 🎯 MVP

**Goal**: desde el detalle de un contenido, seleccionar una o varias cuentas activas del
proyecto y, opcionalmente, una fecha, y crear una publicación por cuenta sin duplicar el
archivo; verlas en una lista básica de la Queue.

**Independent Test**: en "L4i4", crear para un contenido tres publicaciones (Instagram,
TikTok, X) en una operación; existen tres `unscheduled` apuntando al mismo contenido, el
número de archivos almacenados no cambia y tras reiniciar siguen ahí.

### Tests for User Story 1 ⚠️

- [X] T013 [P] [US1] Create `backend/tests/test_publications_create.py` with:
  - One account, no date → `201`, one item: `status == "unscheduled"`,
    `scheduled_at is None`, `project_id`/`content_id`/`account_id` correct, all overrides
    `None`, effective metadata equal to the content's, `account.platform` correct,
    `created_at == updated_at`.
  - Three accounts → three items in `account_ids` order, same `content_id`, distinct
    `account_id`; repeated ids (`[a, a, b]`) → two items.
  - With `scheduled_at = FUTURE` → all `scheduled` with that instant (UTC); a value with
    an offset (`2100-01-01T12:00:00+02:00`) is returned as `2100-01-01T10:00:00Z`; seconds
    are truncated (`…10:00:42Z` → `…10:00:00Z`).
  - No new file: the number of files under `media_dir/projects/{id}/` is unchanged.
  - Rejections (nothing created in any case, checked via `GET
    /api/projects/{id}/publications`):
    - unknown content → `404 not_found`;
    - empty `account_ids` and 51 ids → `422` with field `account_ids`;
    - account of another project → `422 validation_error`, `fields[0] ==
      {"field": "account_ids", "message": "Account {id} does not belong to this project."}`;
    - unknown account id → `422 validation_error` with message "Account {id} not found.";
      a request with one unknown and one other-project account → two distinct entries;
    - inactive account → `409 account_inactive` naming the account in `fields`;
    - inactive project → `409 project_inactive`;
    - `scheduled_at = PAST` → `422` field `scheduled_at`; without time zone
      (`2100-01-01T10:00`) → `422` with `fields == [{"field": "scheduled_at", "message":
      "Include a time zone."}]`;
    - stored file deleted (`stored_file`) → `409 media_unavailable` with message "The media
      file of this content is not available.";
    - atomicity: one valid + one inactive account → error and **zero** publications.
  - Extra fields (`status`, `project_id`) in the body → `422`.
- [X] T014 [P] [US1] Extend `backend/tests/test_persistence.py`: create three publications
  (one scheduled with `FUTURE`, two unscheduled), dispose the app, recreate it on the same
  `db_path` and `media_dir`, and assert `GET /api/projects/{id}/publications` returns
  identical JSON (relations, statuses and dates). Overrides are added to this test in T034.
  Add a separate UTC test: create a publication with `scheduled_at =
  "2100-03-15T18:45:00+02:00"`, restart the app on the same database, and assert
  `GET /api/publications/{id}` returns `"2100-03-15T16:45:00Z"` and that parsing it gives
  the same instant as the original value (`datetime.fromisoformat` comparison).
- [X] T015 [P] [US1] Create `frontend/src/components/PublicationCreate.test.tsx` using
  `FakeApi`, mounting `ProjectDetail`, opening "Content", selecting a content and clicking
  "Prepare publications":
  - Only the project's **active** accounts are listed as checkboxes (label shows platform,
    `@handle` and display name); inactive accounts and other projects' accounts are not
    selectable.
  - Selecting Instagram, TikTok and X and clicking "Create publications" sends one
    `POST /contents/{id}/publications` with the three ids and no `scheduled_at`, then shows
    "Created 3 publications" listing the accounts and an "Open queue" button.
  - Filling the date/time input sends `scheduled_at` as the ISO instant of that local time.
  - "Create publications" is disabled while nothing is selected.
  - Inactive project → the form is replaced by "Reactivate the project to prepare
    publications."; no active accounts → "Add an active account to this project first.";
    `file_available: false` → "The media file of this content is not available."
  - A `409` error response shows its message and the per-account `fields` messages, and
    keeps the selection.
  - "Open queue" switches `ProjectDetail` to the Queue view, which lists the three new
    publications.

### Implementation for User Story 1

- [X] T016 [US1] Implement `POST /api/contents/{content_id}/publications` (`status_code=201`,
  `response_model=list[PublicationRead]`) in `backend/app/publications.py`, following
  [research.md §6](research.md#6-errores-de-la-creación-múltiple-fr-006-fr-007):
  1. `get_content_or_404`; load its project; inactive → `project_inactive`; file not
     available → `media_unavailable`;
  2. `scheduled_at` (if given) → `ensure_future`;
  3. dedupe `account_ids` preserving order; load those accounts in one query;
  4. build per-account problems: missing → 422 entry "Account {id} not found.";
     `project_id` mismatch → 422 entry "Account {id} does not belong to this project.";
     inactive → `account_inactive` entry
     "{Platform} @{handle} is inactive.";
  5. raise the most severe group (`field_errors(...)` for 422, otherwise
     `ConflictError(code, message, fields=[...])`) with general messages "Some accounts
     cannot be used for this content." / "Some accounts are inactive.";
  6. insert one `Publication` per account (`status` from `scheduled_at`, overrides `None`,
     `created_at == updated_at == utc_now()`), single `session.commit()`;
  7. return them with `publication_to_read`.

  (The duplicate check of step 4 is added in US2.)
- [X] T017 [US1] Implement `GET /api/projects/{project_id}/publications` in
  `backend/app/publications.py`: `get_project_or_404`; one `select(Publication, Content,
  Account)` with joins filtered by `project_id`, ordered with
  `case((status == scheduled, 0), (status == unscheduled, 1), else_=2)`, then
  `scheduled_at` asc for scheduled, `created_at` asc for unscheduled, `updated_at` desc for
  cancelled, then `id` (contract order); cache `file_available` per content id. Also
  implement `GET /api/publications/{publication_id}`.
- [X] T018 [US1] Create `frontend/src/components/PublicationCreate.tsx` (props: `project`,
  `content`, `onCreated`, `onOpenQueue`):
  - loads `listAccounts(project.id)` and `listPublications(project.id)`;
  - shows the blocking messages of T015 instead of the form when applicable;
  - a fieldset "Target accounts" with one checkbox per active account (`platformLabel`,
    `@handle`, display name);
  - an optional `<input type="datetime-local">` labelled "Publish at (optional)";
  - submit "Create publications" disabled with no selection or while saving; sends
    `fromDateTimeLocalValue` when the date is filled;
  - on success shows "Created N publications for …" and an "Open queue" button; on error
    uses `FormError` (general message plus every `fields` message), keeping the form state.
- [X] T019 [US1] Wire the flow:
  - `frontend/src/components/ContentDetail.tsx`: a "Prepare publications" button that
    toggles `PublicationCreate` below the metadata; new props `project` and `onOpenQueue`;
  - `frontend/src/components/ContentLibrary.tsx`: pass `project` and `onOpenQueue` through;
  - `frontend/src/components/ProjectDetail.tsx`: view becomes
    `"accounts" | "content" | "queue"` with a third "Queue" button; `onOpenQueue` sets
    `view = "queue"`.

  Depends on T018.
- [X] T020 [US1] Create a basic `frontend/src/components/PublicationQueue.tsx` (props:
  `project`) that loads `listPublications` and renders a list (`aria-label="Publication
  queue"`) with, per row, content title or original filename, platform, `@handle`, status
  label and local date (`formatDate`) when present; load errors with `role="alert"`.
  Grouping, previews, warnings and the detail come in US3/US4. Render it from
  `ProjectDetail` when `view === "queue"`.

**Checkpoint**: US1 tests pass; three publications can be created from the UI and seen in
the Queue; nothing is duplicated on disk.

---

## Phase 4: User Story 2 - Evitar publicaciones activas duplicadas (Priority: P1)

**Goal**: impedir dos publicaciones activas para la misma pareja contenido + cuenta,
informando claramente, sin que las canceladas bloqueen.

**Independent Test**: crear una publicación en Instagram; repetir → `409 duplicate` sin
crear nada; con varias cuentas donde una choca → nada creado y la cuenta identificada; en la
UI la cuenta aparece como ya activa y no seleccionable.

### Tests for User Story 2 ⚠️

- [X] T021 [P] [US2] Add to `backend/tests/test_publications_create.py`:
  - existing `unscheduled` for (content, Instagram) → creating again → `409 duplicate`,
    `fields` has one `account_ids` entry mentioning "Instagram @…"; total count unchanged;
  - existing `scheduled` → same result;
  - `[instagram (conflict), tiktok (free)]` → `409 duplicate`, zero new publications;
  - severity: `[other-project account, inactive account, conflicting account]` →
    `422 validation_error` with three `fields` entries;
  - same account but a **different content** → allowed;
  - race: monkeypatch `find_active` to return `[]` so the partial index fires on commit →
    `409 duplicate` and no extra row.
  (The "cancelled does not block" case is tested in US6.)
- [X] T022 [P] [US2] Add to `frontend/src/components/PublicationCreate.test.tsx`: with an
  existing active publication of the content for Instagram, its checkbox is disabled with
  "Already has an active publication"; a cancelled one does not disable it; a
  `409 duplicate` from the server shows the per-account message.

### Implementation for User Story 2

- [X] T023 [US2] In `backend/app/publications.py`, add the duplicate check to the creation
  (step 4 of T016): `find_active(session, content.id, account_ids)` → one `duplicate`
  entry per account "{Platform} @{handle} already has an active publication of this
  content." (severity below `account_inactive`), general message "Some accounts already
  have an active publication of this content."; wrap the commit in `try/except
  IntegrityError` → `session.rollback()` and `ConflictError("duplicate", …)`.
- [X] T024 [US2] In `frontend/src/components/PublicationCreate.tsx`, disable (and uncheck)
  the accounts that have an active (`unscheduled`/`scheduled`) publication of this content
  according to the loaded list, with the note "Already has an active publication"; reload
  the list after a successful creation.

**Checkpoint**: no se pueden crear duplicados activos ni por API ni por UI.

---

## Phase 5: User Story 3 - Programar y desprogramar publicaciones individualmente (Priority: P1)

**Goal**: asignar, cambiar o quitar la fecha de cada publicación por separado, con
validación de fecha futura y de proyecto/cuenta/archivo.

**Independent Test**: tres publicaciones creadas juntas; programar Instagram y TikTok con
fechas distintas, dejar X sin fecha; quitar después la fecha de TikTok → `unscheduled`.

### Tests for User Story 3 ⚠️

- [X] T025 [P] [US3] Create `backend/tests/test_publications_update.py` with scheduling cases:
  - `PATCH {"scheduled_at": FUTURE}` on `unscheduled` → `scheduled`; other publications of
    the same content unchanged;
  - change to `LATER` → still `scheduled` with the new date; `PATCH {"scheduled_at": null}`
    → `unscheduled`, `scheduled_at` null;
  - `PAST` → `422` field `scheduled_at`, publication unchanged; no time zone → `422`;
    invalid string → `422`;
  - offset and seconds are normalised as in creation;
  - idempotency: re-sending the same `scheduled_at` keeps `updated_at`; and for a publication
    whose `scheduled_at` was set directly in the DB to `PAST` (overdue), re-sending that same
    value is accepted (`200`) and `updated_at` does not change;
  - restrictions when the date **changes**: inactive project → `409 project_inactive`;
    inactive account → `409 account_inactive`; stored file deleted → `409
    media_unavailable`; in all three, `PATCH {"scheduled_at": null}` still works;
  - non-editable fields (`content_id`, `account_id`, `project_id`, `status`) → `422`;
    empty body → `422`;
  - unknown id → `404`; `GET /api/publications/{id}` returns the publication;
  - no automatic transition: a `scheduled` publication whose date was set to `PAST` in the DB
    is still `scheduled` when read and listed.
- [X] T026 [P] [US3] Create `frontend/src/components/PublicationQueue.test.tsx` with
  scheduling cases (mount `ProjectDetail`, open "Queue", click a row to open its detail):
  - setting a date and clicking "Save date" sends `PATCH` with the ISO instant and the row
    shows "Scheduled" with the local date;
  - "Remove date" sends `scheduled_at: null` and the row moves to "Unscheduled";
  - a `422` on `scheduled_at` is shown next to the date input without losing the value;
  - with an inactive account or project, or `file_available: false`, "Save date" is
    disabled with the reason, while "Remove date" stays enabled.

### Implementation for User Story 3

- [X] T027 [US3] Implement `PATCH /api/publications/{publication_id}` (scheduling part) in
  `backend/app/publications.py`:
  - `get_publication_or_404`; `cancelled` → `ConflictError("publication_cancelled",
    "Reactivate the publication before editing it.")`;
  - if `"scheduled_at" in body.model_fields_set` and the value differs from the stored one:
    when not `None`, `ensure_future` and `ensure_can_prepare`; set `scheduled_at` and
    `status` (`scheduled` / `unscheduled`);
  - `updated_at = utc_now()` and commit only if something changed; return
    `publication_to_read`.
- [X] T028 [US3] Create `frontend/src/components/PublicationDetail.tsx` (props:
  `publication`, `onChanged: () => Promise<void>`) with the scheduling section: status
  badge, current local date, a `datetime-local` input initialised with
  `toDateTimeLocalValue`, "Save date" and "Remove date" buttons, disabled states with the
  reason ("Reactivate the project…", "Reactivate the account…", "The media file of this
  content is not available."), and `FieldMessage`/`FormError` for errors. In
  `PublicationQueue.tsx`, make each row a button that selects the publication and renders
  `PublicationDetail` below the list, reloading the list after each change.

**Checkpoint**: P1 completo — crear, sin duplicados, programar y desprogramar por API y UI.

---

## Phase 6: User Story 4 - Consultar la Queue del proyecto (Priority: P2)

**Goal**: Queue agrupada (Scheduled, Unscheduled, Cancelled) con preview, plataforma,
cuenta, estado, fecha y avisos, en el orden del contrato.

**Independent Test**: un proyecto con publicaciones en los tres estados muestra las tres
secciones en orden, con previews y avisos; un proyecto sin publicaciones muestra el estado
vacío; un proyecto inactivo sigue mostrando su Queue.

### Tests for User Story 4 ⚠️

- [X] T029 [P] [US4] Create `backend/tests/test_publications_queue.py`:
  - empty project → `[]`; unknown project → `404`;
  - order: scheduled by date (`LATER` after `FUTURE`, ties by `id`), then unscheduled by
    `created_at`, then cancelled with the most recently cancelled first;
  - only that project's publications;
  - cancelled publications and publications of inactive accounts are included, with
    `account.is_active == false`;
  - inactive project → `200` with `project_active == false` on each item;
  - summaries: `content.file_url`, `content.file_available` (false after deleting the stored
    file), `account.platform`/`handle`;
  - volume (SC-008, functional only): 200 publications (200 contents × 1 account, or
    fewer contents × several accounts) → `200` with 200 items in order; no time threshold.
- [X] T030 [P] [US4] Add to `frontend/src/components/PublicationQueue.test.tsx`:
  - empty project → "No publications yet. Open a content and choose Prepare publications.";
  - three headed sections "Scheduled (n)", "Unscheduled (n)", "Cancelled (n)" in that
    order, each row with preview (`<img>`/`<video>` or "File not available"), title or
    original filename, platform, `@handle`, status label and local date;
  - "Overdue" shown for a `scheduled` publication with a past date; "Account inactive" for
    an inactive account;
  - inactive project → Queue still listed;
  - volume: 200 publications render 200 rows.

### Implementation for User Story 4

- [X] T031 [US4] Extend `frontend/src/components/PublicationQueue.tsx`: three sections with
  headings and counters (keeping the API order inside each), empty state, a small
  `MediaPreview` (reuse from `ContentDetail.tsx`, adapting its prop type to accept the
  content summary fields it needs: `media_type`, `file_url`, `file_available`), badges
  "Overdue" (`isOverdue`), "Account inactive" and "Project inactive".
- [X] T032 [US4] Add Queue styles to `frontend/src/index.css` (compact rows with a small
  fixed-size preview, status badges with distinct classes `status-scheduled`,
  `status-unscheduled`, `status-cancelled`, warning badge style).

**Checkpoint**: Queue completa y legible.

---

## Phase 7: User Story 5 - Personalizar la metadata de una publicación (Priority: P2)

**Goal**: overrides por campo de título, descripción y hashtags, distinguiendo "usar
metadata global" de "override propio" (incluido vacío), con herencia viva del contenido.

**Independent Test**: personalizar la descripción de Instagram; la metadata del contenido y
de TikTok no cambia; editar el título global se refleja en ambas; Instagram conserva su
descripción.

### Tests for User Story 5 ⚠️

- [X] T033 [P] [US5] Add to `backend/tests/test_publications_update.py`:
  - inherited by default: effective values equal the content's, overrides `None`;
  - `PATCH {"description_override": "Custom"}` → effective description "Custom",
    `description_override == "Custom"`; the content (`GET /api/contents/{id}`) and the
    sibling publication are unchanged;
  - global change reflected: `PATCH /api/contents/{id}` title → every publication without
    title override shows the new title; the one with description override keeps it;
  - empty overrides: `"   "` → `title_override == ""`, effective title `""`;
    `hashtags_override: []` → effective hashtags `[]` while the content has hashtags;
  - reset: `PATCH {"description_override": null}` → inherits again;
  - normalisation: hashtags `["#A", "a", "b"]` → `["A", "b"]`; invalid hashtag or
    201-character title or 5001-character description → `422` with the right field;
  - override equal to the global value stays an override (not `None`) and does not follow a
    later global change;
  - `updated_at` unchanged when re-sending identical normalised overrides; changed
    otherwise;
  - overrides editable with inactive project, inactive account and missing file.
- [X] T034 [P] [US5] Extend `backend/tests/test_persistence.py` (the test of T014): also set a
  description override and an empty hashtags override before restarting and assert they
  survive identically.
- [X] T035 [P] [US5] Add to `frontend/src/components/PublicationQueue.test.tsx`:
  - the detail shows, per field, "Using content value" with the inherited value;
  - "Customize" on Description reveals an editable field prefilled with the inherited value;
    saving sends only `description_override`, and the field shows "Customized";
  - "Use content value" sends `description_override: null`;
  - clearing the hashtags override field and saving sends `hashtags_override: []` and shows
    "No hashtags";
  - a `422` keeps the typed text and shows the field message.

### Implementation for User Story 5

- [X] T036 [US5] Extend `PATCH /api/publications/{publication_id}` in
  `backend/app/publications.py`: for each of `title_override`, `description_override`,
  `hashtags_override` present in `model_fields_set`, assign the validated value (`None`
  resets) when it differs from the stored one (compare `None` vs `""`/`[]` as different),
  contributing to the single `changed` flag; no `ensure_can_prepare` call for overrides.
- [X] T037 [US5] Add the metadata section to
  `frontend/src/components/PublicationDetail.tsx`: one block per field with its mode
  ("Using content value" + inherited value, or "Customized" + input/textarea), toggle
  buttons "Customize" / "Use content value", a "Save metadata" submit sending only the
  changed fields (`parseHashtags` for hashtags; an empty text keeps `""`), and error display
  with `FieldMessage`/`FormError` without losing input.

**Checkpoint**: overrides funcionando con herencia viva.

---

## Phase 8: User Story 6 - Cancelar y reactivar publicaciones (Priority: P2)

**Goal**: cancelar sin perder historial y reactivar cuando no haya conflicto ni
restricciones.

**Independent Test**: cancelar una programada (sigue en Cancelled, deja de ser activa);
crear otra para la misma pareja; reactivar la antigua → `409 duplicate`; cancelar la nueva y
reactivar la antigua → vuelve a su estado.

### Tests for User Story 6 ⚠️

- [X] T038 [P] [US6] Create `backend/tests/test_publications_lifecycle.py`:
  - cancel `unscheduled` and `scheduled` → `cancelled`, `scheduled_at` and overrides kept,
    `updated_at` changed; cancel again → `200`, `updated_at` unchanged;
  - cancel allowed with inactive project, inactive account and missing file;
  - `PATCH` on a cancelled one → `409 publication_cancelled`;
  - cancelled does not block: after cancelling, creating for the same pair → `201`;
  - reactivate: with future date → `scheduled`; without date → `unscheduled`; with a past
    date (set in the DB) → `unscheduled` and `scheduled_at` null;
  - reactivate conflicts: another active publication for the pair → `409 duplicate`;
    inactive project → `409 project_inactive`; inactive account → `409 account_inactive`;
    missing file → `409 media_unavailable`; not cancelled → `409 publication_not_cancelled`;
  - cancel/reactivate unknown id → `404`; `DELETE /api/publications/{id}` → `405`.
- [X] T039 [P] [US6] Add to `frontend/src/components/PublicationQueue.test.tsx`:
  - "Cancel publication" moves the row to "Cancelled" and the detail becomes read-only with
    a "Reactivate" button;
  - "Reactivate" returns it to Scheduled/Unscheduled; when the API returns
    `scheduled_at: null` for a publication that had a date, the notice "The scheduled date
    had passed and was removed. Choose a new date." is shown;
  - a `409 duplicate` on reactivate shows its message;
  - "Reactivate" disabled with the reason for inactive project/account or missing file;
  - there is no delete action.

### Implementation for User Story 6

- [X] T040 [US6] Implement `POST /api/publications/{publication_id}/cancel` and
  `POST /api/publications/{publication_id}/reactivate` in `backend/app/publications.py`
  following [contracts/api.md](contracts/api.md) and [data-model.md](data-model.md):
  - cancel: no-op if already `cancelled`; otherwise `status = cancelled`, `updated_at`;
  - reactivate: not cancelled → `publication_not_cancelled` ("This publication is not
    cancelled."); `ensure_can_prepare`; `find_active(..., exclude_id=publication.id)` →
    `duplicate` ("{Platform} @{handle} already has an active publication of this
    content."); then `scheduled` if `scheduled_at > utc_now()`, else `scheduled_at = None`
    and `unscheduled`; commit with `IntegrityError` → `duplicate` as in T023.
- [X] T041 [US6] Add to `frontend/src/components/PublicationDetail.tsx`: "Cancel
  publication" (for active ones) and, for cancelled ones, a read-only view (date and
  overrides shown, inputs hidden) with "Reactivate" (disabled with reason when not allowed)
  and the "date had passed" notice; reload the Queue after each action.

**Checkpoint**: todas las historias funcionan de forma independiente.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T042 [P] Update `README.md`: publications concept (content × account), statuses
  `unscheduled`/`scheduled`/`cancelled`, the Queue view, metadata overrides, the
  "one active publication per content and account" rule, that scheduling only stores the
  intent and nothing is published automatically yet, and the new API routes.
- [X] T043 [P] Review `frontend/src/index.css` and the new components for consistency with
  the existing minimal style (no new libraries), accessible labels on every input and
  button, and `role="alert"` on errors.
- [X] T044 Run all quality gates: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`; fix every failure.
- [X] T045 Run the manual validation of [quickstart.md](quickstart.md) sections 3–7 (reference
  flow SC-001, API rules, inactive/missing-file cases, no automatic execution) and record
  any deviation; confirm `git status` shows no database or media files.

  _Run on 2026-10-06 against a real backend with isolated data: reference flow through the
  API (3 publications, two dates, X unscheduled, Instagram description override, global
  metadata untouched), restart with identical queue, cancel X, new X allowed, old X
  reactivation → `409 duplicate`, one stored file; API rules of §4 return the documented
  codes and messages; `git status` clean of data. The browser walkthrough, the 2-minute
  wait of §6 and the timings of §7 are left to the user._

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; bloquea todas las historias.
- **US1 (Phase 3)**: depende de Foundational. Crea la Queue básica y el flujo desde Content.
- **US2 (Phase 4)**: depende de US1 (amplía la creación y `PublicationCreate`).
- **US3 (Phase 5)**: depende de US1 (necesita publicaciones y la Queue básica para abrir el
  detalle).
- **US4 (Phase 6)**: depende de US1; independiente de US2/US3 en backend. En frontend
  amplía `PublicationQueue.tsx` (coordinar con US3 si se hace en paralelo).
- **US5 (Phase 7)**: depende de US3 (amplía el `PATCH` y `PublicationDetail`).
- **US6 (Phase 8)**: depende de US3 (`PublicationDetail`) y de US2 (regla de duplicados en
  reactivación).
- **Polish (Phase 9)**: depende de todas las historias.

### Within Each User Story

- Tests primero (deben fallar), después backend, después frontend.
- Mismo archivo → secuencial (p. ej. `publications.py`, `PublicationDetail.tsx`).

### Parallel Opportunities

- Phase 2: T002, T004, T005 (backend) en paralelo con T009, T010, T011 (frontend).
- En cada historia, las tareas de test `[P]` (backend y frontend) en paralelo.
- Tras US1: US2 (backend) y US4 (backend) pueden avanzar en paralelo; US3 backend también.

## Parallel Example: User Story 1

```text
# Tests de US1 en paralelo:
T013 backend/tests/test_publications_create.py
T014 backend/tests/test_persistence.py
T015 frontend/src/components/PublicationCreate.test.tsx

# Después, backend y frontend en paralelo:
T016 + T017 backend/app/publications.py
T018 frontend/src/components/PublicationCreate.tsx
```

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 + Phase 2.
2. Phase 3 (US1): crear publicaciones para varias cuentas y verlas en la Queue básica.
3. **Validar**: tests de US1 y pasos 1–5 del flujo de referencia.

### Incremental Delivery

1. US1 → US2 (sin duplicados) → US3 (programación): P1 completo; pasos 1–8 del flujo de
   referencia salvo la personalización.
2. US4 (Queue completa) → US5 (overrides) → US6 (cancelar/reactivar): flujo de referencia
   completo (SC-001).
3. Polish: README, quality gates y quickstart manual.

### Notes

- Commits pequeños en inglés por tarea o grupo lógico.
- No ampliar el alcance: nada de scheduler, ejecución automática, adaptadores, calendario
  ni `DELETE`.
