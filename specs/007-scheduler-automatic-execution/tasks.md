---

description: "Task list for the scheduler and automatic execution of scheduled publications"
---

# Tasks: Scheduler y ejecución automática de publicaciones programadas

**Input**: Design documents from `specs/007-scheduler-automatic-execution/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-044, SC-013). Reloj falso (`FakeClock`),
espera inyectable, `Scheduler.run_once()` llamado a mano, publishers simulados
(`FakePublisher`) y el simulador de YouTube de la Feature 006. Ningún test sube vídeos
reales, usa Internet, el llavero del sistema ni esperas reales largas. En cada fase los
tests se escriben primero y deben fallar antes de implementar.

**Organization**: tareas agrupadas por historia de usuario (US1–US8 de la spec). Código,
comentarios, mensajes de API y UI, README y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes).
- **[Story]**: historia de usuario a la que pertenece (US1–US8).

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`.
- Frontend: `frontend/src/`, `frontend/src/components/`.
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- **Un solo servicio de ejecución**: el scheduler inicia publicaciones exclusivamente con
  `app.publishing.start_publication(..., trigger=AttemptTrigger.SCHEDULED, clock=settings.clock)`,
  invocado directamente (sin HTTP). Nunca reimplementa preflight, transición ni subida.
- **Núcleo genérico** (Constitution III): `app/scheduler.py`, `app/automation.py`,
  `app/publishing.py` y `app/publications.py` no importan `app.youtube_*`,
  `app.credential_store`, `httpx`, `httpx2` ni `keyring`. Ningún dato nuevo es específico de
  una plataforma.
- **Consentimiento**: `publications.auto_publish_enabled = 1` solo con `status = 'scheduled'`
  (CHECK). Toda escritura que saca una publicación de `scheduled` la desarma y limpia el
  fallo automático en la misma transacción. Una fecha nueva sin `auto_publish_enabled`
  explícito queda desarmada.
- **Reclamación atómica** (research §5, data-model §5): para `trigger = scheduled`, el
  `UPDATE` de `create_running_attempt` re-comprueba **tras el preflight** y en la misma
  transacción que inserta el intento: `status = 'scheduled'`, `auto_publish_enabled = 1`,
  `automation_paused = 0`, `scheduled_at <= now <= scheduled_at + 10 min`, sin intento
  `running` de esa publicación y menos de 2 intentos `running` con `trigger = 'scheduled'`.
  `Publish now` (`manual`) nunca lleva estas guardas.
- **Ventana**: `AUTO_PUBLISH_WINDOW = timedelta(minutes=10)`, inclusiva en ambos extremos;
  todo en UTC consciente de zona.
- **Overdue no es un estado**: no existe ningún estado `MISSED`/`missed`. Una publicación que
  pierde su ventana automática **sigue con `status = "scheduled"`**; overdue es una condición
  derivada (`is_overdue(...) == True`, expuesta en la API como
  `auto_publish_state == "overdue"`) que solo se cumple si está **armada** y
  `now > scheduled_at + 10 min`; una desarmada nunca es overdue (`disabled`). La interfaz
  muestra `Missed automatic publishing window`.
- **Fallos automáticos**: solo códigos y mensajes ya existentes y seguros de
  `ConflictError`/`AppError`/`NotFoundError`; cualquier otra excepción → `internal_error` con
  mensaje fijo. Re-comprobación solo cuando `now >= auto_publish_failed_at + 120 s`
  (persistente). Nunca se crea un `PublicationAttempt` por un preflight fallido.
- **Logs**: el scheduler registra ids de publicación, códigos de error y nombres de clase de
  excepción; nunca `str(exc)`, `exc_info`, tokens, URIs de sesión ni video IDs.
- **Sin retries entre intentos**: nada reacciona a `failed`.
- **Errores HTTP**: formato existente `{"error": {"code", "message", "fields"}}`.
- **Catálogos duplicados** backend (`StrEnum`) ↔ frontend (`types.ts`), con un comentario en
  cada lado que apunte al otro: `AttemptTrigger`, `AutoPublishState`.
- **Tests deterministas**: sin `time.sleep` reales salvo esperas acotadas con `Event`; el
  hilo del scheduler solo se arranca en `test_scheduler_lifecycle.py`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: línea base. No hay dependencias nuevas (plan, Technical Context).

- [X] T001 Verify the baseline on branch `007-scheduler-automatic-execution`: run `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`. All must pass before any change; record any pre-existing failure instead of fixing it silently.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: migración y modelo, reglas puras de automatización, reclamación atómica en el
núcleo, invariante de desarmado, esqueleto del scheduler, cableado en `main.py`, soporte de
tests y tipos del frontend.

**⚠️ CRITICAL**: no se puede empezar ninguna historia hasta completar esta fase.

### Tests fundacionales (escribir primero)

- [X] T002 [P] Extend `backend/tests/test_migrations.py` (fail before T005):
  - a database populated at `0005` with publications `scheduled` (past date, date within the last 10 minutes, future date), `unscheduled`, `failed`, `published`, `cancelled` and attempts `succeeded`/`failed` upgrades to `0006` keeping every row;
  - after `0006`: every publication has `auto_publish_enabled = 0` and NULL `auto_publish_error_code`/`auto_publish_error_message`/`auto_publish_failed_at`; every attempt has `trigger = 'manual'`; `automation_settings` has exactly one row `(id=1, automation_paused=0)`;
  - constraints: `auto_publish_enabled = 1` with a status other than `scheduled` fails `ck_publications_auto_publish_only_scheduled`; error columns set while not armed fail `ck_publications_auto_publish_error_only_armed`; partially set error columns fail `ck_publications_auto_publish_error_pair`; `trigger = 'other'` fails `ck_publication_attempts_trigger_valid`; a second `automation_settings` row or `id = 2` fails;
  - index `ix_publications_status_auto_publish_scheduled_at` exists; `downgrade` to `0005` removes everything added; the models-vs-migrations drift test passes;
  - running the migration never calls any publisher nor the Google transport (assert with a fake transport that fails on any request).
- [X] T003 [P] Write `backend/tests/test_automation_state.py` (pure functions, fail before T006), with `scheduled_at = 2026-10-07T18:00:00Z`:
  - `auto_publish_state`: `None` for every status other than `scheduled`; not armed → `disabled` both before and long after the date (`is_overdue` always `False`); armed: 17:59:59 → `waiting`, 18:00:00 → `due`, 18:09 → `due`, 18:10:00 → `due` (`is_overdue` `False`), 18:10:00.000001 → `is_overdue` `True` / `overdue`; armed + paused before the window end → `paused`; armed + paused after the window end → `is_overdue` `True` / `overdue`; no function ever returns a publication status other than the given one;
  - `window_ends_at` = `scheduled_at + 10 min`; `in_window` inclusive at both ends;
  - `auto_start_blocker(...)` returns `None` only for scheduled + armed + not paused + in window, and a reason otherwise;
  - the same instant expressed as `2026-10-25T02:30:00+02:00` and `2026-10-25T00:30:00Z` (Europe/Madrid DST change) gives identical results; times around the repeated local hour are evaluated purely in UTC.
- [X] T004 [P] Extend the architecture test in `backend/tests/test_publications_states.py`: `app.scheduler` and `app.automation` (in addition to `app.publishing` and `app.publications`) import nothing from `app.youtube_*`, `app.credential_store`, `httpx`, `httpx2` or `keyring` (via `ast`). Fails until T006/T010 create the modules.

### Implementación fundacional

- [X] T005 Update `backend/app/models.py` and add the migration ([data-model.md §1–§3, §9](data-model.md)):
  - `Publication`: `auto_publish_enabled: Mapped[bool]` (`server_default=sa.false()`, not null), `auto_publish_error_code` (`String(40)`), `auto_publish_error_message` (`String(500)`), `auto_publish_failed_at` (`UTCDateTime`), the three CHECKs and the index `ix_publications_status_auto_publish_scheduled_at`;
  - `AttemptTrigger(StrEnum)` (`MANUAL = "manual"`, `SCHEDULED = "scheduled"`, comment pointing to `frontend/src/types.ts`) and `PublicationAttempt.trigger` (`String(20)`, `server_default="manual"`, CHECK `trigger_valid`);
  - new model `AutomationSettings` (`automation_settings`: `id` PK with CHECK `id = 1`, `automation_paused: Mapped[bool]` default false, `updated_at`);
  - `backend/migrations/versions/0006_automatic_publishing.py` (`down_revision = "0005"`): batch-alter `publications` (`recreate="always"`) and `publication_attempts`, create `automation_settings` and insert `(1, false, now_utc)`; working `downgrade()`. Only SQLite statements. Makes T002 pass.
- [X] T006 Create `backend/app/automation.py` (generic; imports only `app.models`, `app.db`, `app.errors`, `app.schemas`, SQLAlchemy, FastAPI and the standard library):
  - `AUTO_PUBLISH_WINDOW = timedelta(minutes=10)`, `AUTO_PUBLISH_RETRY_INTERVAL = timedelta(seconds=120)`, `DEFAULT_MAX_CONCURRENT_SCHEDULED = 2`;
  - `AutoPublishState(StrEnum)` (derived, never persisted: `disabled`, `waiting`, `due`, `paused`, `overdue`; comment pointing to `types.ts`);
  - pure functions `window_ends_at(scheduled_at)`, `in_window(scheduled_at, now)`, `is_overdue(status, armed, scheduled_at, now) -> bool` (`status == scheduled` and armed and `now > scheduled_at + 10 min`), `auto_publish_state(status, armed, scheduled_at, paused, now)`, `auto_start_blocker(publication, paused, now) -> str | None`;
  - `is_paused(session) -> bool` (missing row → `True` + `logger.warning`), `set_paused(session, paused, now)` (upsert of row 1);
  - `scheduled_claim_conditions(now, max_concurrent) -> list[ColumnElement[bool]]`: status, armed, `NOT EXISTS` paused row, window bounds, `NOT EXISTS` running attempt of the same publication, scalar subquery count of running `scheduled` attempts `< max_concurrent` ([research.md §5](research.md));
  - `disarm_values() -> dict` with `auto_publish_enabled=False` and the three error columns `None` (reused by every transition out of `scheduled`);
  - `get_clock(request) -> Callable[[], datetime]` reading `request.app.state.clock`;
  - an empty `router = APIRouter(prefix="/api", tags=["automation"])` (endpoints added in US4).
  Makes T003 pass.
- [X] T007 Extend `backend/app/publishing.py` (no new imports outside `app.automation`):
  - `create_running_attempt(session, publication, prepared, platform, *, trigger=AttemptTrigger.MANUAL, clock: Callable[[], datetime] = utc_now, max_concurrent=DEFAULT_MAX_CONCURRENT_SCHEDULED)`: it calls `clock()` itself immediately before the `UPDATE` (never receives a fixed instant); the `UPDATE` sets `status='publishing'`, `updated_at`, **and** `disarm_values()`; for `MANUAL` the `WHERE` stays `status IN ELIGIBLE_STATUSES` (no pause/window/slot guards); for `SCHEDULED` it adds `scheduled_claim_conditions(claim_now, max_concurrent)`; the attempt is inserted with `trigger=trigger` in the same transaction; `rowcount != 1` keeps raising `publication_in_progress` / `publication_not_eligible` via `_not_startable`;
  - `start_publication(..., trigger=AttemptTrigger.MANUAL, clock: Callable[[], datetime] = utc_now, max_concurrent=...)`: never receives a fixed `now`; for `SCHEDULED`, before `local_check` call `auto_start_blocker(publication, is_paused(session), clock())` and raise `ConflictError("publication_not_eligible", ...)` if blocked; force `confirm_remote_checked=False`; pass the same `clock` to `create_running_attempt`, so the time is read again **after** `publisher.prepare`, just before the atomic claim;
  - `publish_now` keeps calling it with defaults (manual).
- [X] T008 Keep the disarm invariant and the derived fields in `backend/app/publications.py` (no new request fields yet):
  - `cancel_publication`, and `update_publication` when `scheduled_at` changes (including to `null`), apply `disarm_values()`; `reactivate_publication` leaves the publication disarmed;
  - **one mapper for every response**: `publication_to_read(..., *, now: datetime, paused: bool)` computes `auto_publish_enabled`, `auto_publish_state` (including the overdue condition via `is_overdue`), `auto_publish_window_ends_at` and the current `auto_publish_error` (`{code, message, failed_at}` or `null`); `publication_read(session, publication, storage, clock)` / `_to_read` read `is_paused(session)` and `clock()` once and delegate to it; `list_publications` reads both once per request and passes them to `publication_to_read` for each row;
  - every endpoint returning a `Publication` uses that mapper with the app clock (`ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]`): create (`POST /api/contents/{id}/publications`), `GET`, `PATCH` (date/arming/overrides), `cancel`, `reactivate`, and `POST /api/publications/{id}/publish` in `backend/app/publishing.py` (`publish_now` receives `ClockDep` and calls `publication_read(..., clock)`); no endpoint computes derived fields on its own.
- [X] T009 Update `backend/app/schemas.py`: `PublicationRead` + `auto_publish_enabled: bool`, `auto_publish_state: AutoPublishState | None`, `auto_publish_window_ends_at: datetime | None`, `auto_publish_error: AutoPublishErrorRead | None` (`code`, `message`, `failed_at`); `PublicationAttemptRead.trigger: AttemptTrigger`; `AutomationStatusRead` (`paused`, `running`, `last_check_at`, `check_interval_seconds`, `window_minutes`); `AutomationUpdate` (`paused: bool`, required, `extra="forbid"`). `attempt_to_read` fills `trigger`.
- [X] T010 Create `backend/app/scheduler.py` skeleton (generic; imports `app.publishing`, `app.automation`, `app.models`, `app.errors`, SQLAlchemy and the standard library only):
  - `SchedulerSettings` (frozen dataclass): `clock = utc_now`, `interval = 30.0`, `wait: Callable[[float], bool] | None = None`, `autostart = True`, `max_concurrent = 2`, `preflight_retry_interval = 120.0`, `stop_timeout = 5.0`;
  - `TickReport` dataclass (`started`, `failed`, `skipped_capacity`, `skipped_retry` lists of ids);
  - `Scheduler(session_factory, ctx, runner, publishers, settings)` with `run_once() -> TickReport` (empty for now), `start()`, `stop()`, `wake()`, properties `running` and `last_check_at`; the thread (`name="publication-scheduler"`, daemon) runs `run_once()` immediately and then waits `interval` using `settings.wait` or `stop_event.wait`, waking early on `wake_event`; every tick wrapped in `try/except Exception` logging only the class name; `last_check_at` set to `clock()` after a tick without global exception; `stop()` sets the event and joins up to `stop_timeout`.
- [X] T011 Wire the composition root in `backend/app/main.py`: `create_app(..., scheduler_settings: SchedulerSettings | None = None, clock: Callable[[], datetime] | None = None)`; `app.state.clock = clock or (scheduler_settings.clock if provided) or utc_now` (single clock for API and scheduler); lifespan order: `run_migrations` → engine/session factory/storage → `PublishContext`, `PublicationRunner`, `app.state.publishers` → `recover_interrupted_attempts(session_factory)` (moved after the publishers) → `Scheduler(...)` in `app.state.scheduler` → `scheduler.start()` if `autostart`; in `finally`: `scheduler.stop()` **before** `runner.stop()`; `app.include_router(automation.router)`.
- [X] T012 [P] Extend test support:
  - `backend/tests/fakes.py`: `FakeClock` (mutable, `now()`, `advance(seconds)`, `set(dt)`), and `FakePublisher` implementing the `Publisher` protocol: programmable local problems for `check`, programmable exceptions for `prepare` (`ConflictError`/`AppError`/`RuntimeError`), optional `threading.Barrier`/`Event` inside `prepare`, an `upload` that can succeed, raise `PublishFailure`, or block on an `Event`; counters of `check`/`prepare`/`upload` calls per publication id;
  - `backend/tests/conftest.py`: fixtures `fake_clock`, `scheduler_app` / `scheduler_client` (`create_app(..., scheduler_settings=SchedulerSettings(autostart=False, clock=fake_clock.now), clock=fake_clock.now, publishing_settings=no-sleep)` with the YouTube simulator, plus a variant registering `FakePublisher` for `Platform.YOUTUBE`), helpers `arm(db_path, publication_id)` (SQL update used until US2 exposes the API), `run_tick(app) -> TickReport`, `wait_attempts_idle(app)`, `scheduled_publication(client, at=...)`.
- [X] T013 [P] Update `frontend/src/types.ts` (`AttemptTrigger`, `AutoPublishState`, `AutomationStatus`, `AutoPublishError`; `Publication` + `auto_publish_enabled`, `auto_publish_state`, `auto_publish_window_ends_at`, `auto_publish_error`; `PublicationAttempt.trigger`; comments pointing to `models.py`/`automation.py`), `frontend/src/api.ts` (`getAutomation()`, `setAutomationPaused(paused)`; `PublicationCreate` and `PublicationUpdate` accept `auto_publish_enabled`) and `frontend/src/test-fake-api.ts` (defaults for the new fields, automation state, recorded calls).

**Checkpoint**: migración, reglas puras, reclamación atómica y esqueleto del scheduler listos;
T002–T004 en verde; el resto de la suite sigue en verde.

---

## Phase 3: User Story 1 - Publicación automática a la hora programada (Priority: P1) 🎯 MVP

**Goal**: una publicación armada y válida se inicia sola al llegar su hora mediante el
servicio genérico y termina `PUBLISHED`, con intento `trigger = scheduled`.

**Independent Test**: con `FakeClock` y el simulador de YouTube, armar (helper `arm`) una
publicación para dentro de 5 min, llamar a `run_once()` antes de la hora (nada) y a la hora
(`publishing` → `published`, un intento `scheduled`). En el frontend, con temporizadores
falsos, la Queue y el detalle abiertos sobre una publicación armada pasan a `Publishing`
sin recarga manual cuando el sondeo devuelve el nuevo estado.

### Tests for User Story 1 ⚠️

- [X] T014 [P] [US1] Write `backend/tests/test_scheduler_tick.py` (happy path, fail before T016): future armed publication → `run_once()` starts nothing and calls neither `check` nor `prepare`; at `scheduled_at` → one attempt with `trigger = "scheduled"`, publication `publishing`, then `published` after `wait_attempts_idle` with the YouTube simulator; `start_publication` is called directly (patch-spy on `app.publishing.start_publication`; no HTTP request made by the scheduler); consecutive ticks afterwards start nothing; `FAILED` from the upload (simulator definitive 4xx) stays `failed` and later ticks never create a second attempt; a `Publish now` attempt keeps `trigger = "manual"`.
- [X] T015 [P] [US1] Extend `frontend/src/components/PublicationDetail.test.tsx` and `frontend/src/components/PublicationQueue.test.tsx` (fail before T017):
  - `PublicationAttempts` (rendered in the detail) shows `Started by scheduler` for `trigger: "scheduled"` and `Started manually` for `"manual"`;
  - **functional refresh** with fake timers: while the open publication (detail) or any listed publication (Queue) is `scheduled` with `auto_publish_enabled: true` and is not overdue, the component re-fetches every 15 s (`AUTOMATION_POLL_INTERVAL_MS`); when a re-fetch returns `publishing`, the status changes without manual reload and the existing 2 s polling of Feature 006 takes over; with no armed (non-overdue) or publishing publication there is no polling.

### Implementation for User Story 1

- [X] T016 [US1] Implement `Scheduler.run_once()` in `backend/app/scheduler.py`: read `now = clock()`; select candidates with one query (`status='scheduled'`, `auto_publish_enabled=1`, window bounds) ordered by `scheduled_at, id`; for each, in its own session, call `start_publication(session, id, confirm_remote_checked=False, ctx, runner, publishers, trigger=SCHEDULED, clock=settings.clock, max_concurrent=settings.max_concurrent)`; catch `ConflictError` with `publication_in_progress`/`publication_not_eligible` silently (debug log); log `INFO` "Started publication %s automatically." on success; fill `TickReport`; check `stop_event` between candidates. Pause, retry throttle, error recording and slot pre-check are added in US4, US6 and US7. Makes T014 pass.
- [X] T017 [US1] Frontend for US1, making T015 pass:
  - `frontend/src/components/PublicationAttempts.tsx`: show the attempt origin (`Started manually` / `Started by scheduler`);
  - `frontend/src/components/PublicationDetail.tsx` and `frontend/src/components/PublicationQueue.tsx`: add `AUTOMATION_POLL_INTERVAL_MS = 15000` and poll `getPublication` / `listPublications` at that interval while an armed, non-overdue `scheduled` publication is shown (`auto_publish_state` `waiting`, `due` or `paused`); keep the existing 2 s polling (`POLL_INTERVAL_MS` / `QUEUE_POLL_INTERVAL_MS`) while any is `publishing`, which takes precedence. Only the refresh: labels and badges come in US8.

**Checkpoint**: el scheduler publica sola una publicación armada (armada por SQL en tests) y la
interfaz refleja el inicio sin recargar.

---

## Phase 4: User Story 2 - Consentimiento explícito para la publicación automática (Priority: P1)

**Goal**: solo se ejecuta lo que el usuario arma explícitamente; nada antiguo queda armado;
cancelar/reactivar, reprogramar sin campo, quitar la fecha y `Publish now` desarman.

**Independent Test**: tras la migración nada está armado; armar por API una publicación y
comprobar que solo esa se ejecuta; cancelar/reactivar → desarmada.

### Tests for User Story 2 ⚠️

- [X] T018 [P] [US2] Write `backend/tests/test_auto_publish_consent.py` (fail before T020), following the table of [contracts/api.md](contracts/api.md) (`PATCH`):
  - create with `scheduled_at` + `auto_publish_enabled: true` → armed (`auto_publish_state` `waiting`); `true` without date → `422` field `auto_publish_enabled`; default → disarmed;
  - `PATCH {"auto_publish_enabled": true}` on future `scheduled` → armed; on past date → `422`; on `unscheduled` without date in body → `422`; with inactive project/account or missing media → `409 project_inactive`/`account_inactive`/`media_unavailable`; on `failed`/`cancelled`/`publishing`/`published` → `409`;
  - `PATCH {"scheduled_at": future, "auto_publish_enabled": true|false}` → as requested; `PATCH {"scheduled_at": other future}` without the field → disarmed; `{"scheduled_at": null}` → `unscheduled` disarmed; `{"scheduled_at": null, "auto_publish_enabled": true}` → `422`;
  - `PATCH {"auto_publish_enabled": false}` → disarmed, also with inactive project/account; editing only overrides keeps the armed flag;
  - cancel → disarmed; reactivate (future date) → `scheduled` + `disabled`; `Publish now` on an armed publication → its attempt is `manual` and the publication is no longer armed;
  - end to end with `FakeClock`: an armed and a disarmed publication at the same time → only the armed one starts; a migrated pre-existing scheduled publication (created at `0005`, upgraded) never starts.
- [X] T019 [P] [US2] Extend `frontend/src/components/PublicationCreate.test.tsx` and `frontend/src/components/PublicationDetail.test.tsx`: with a date, the "Publish automatically at this time" checkbox is unchecked by default and the submit says `Save schedule` / create label; checking it switches to `Schedule & enable auto-publish` and shows the explanation ("AutoPublisher will upload this publication automatically when the time comes. It must be running at that time."); the request always carries both `scheduled_at` and `auto_publish_enabled`; the detail of a scheduled publication shows `Enable auto-publish` (opens a confirmation with date and destination before calling the API; disabled for past dates) or `Disable auto-publish`; reactivated publications show `Auto-publish disabled`.

### Implementation for User Story 2

- [X] T020 [US2] Implement the arming rules in `backend/app/publications.py` and `backend/app/schemas.py` (`PublicationCreate.auto_publish_enabled: bool = False`, `PublicationUpdate.auto_publish_enabled: bool | None`): validations and outcomes exactly as T018 / [contracts/api.md](contracts/api.md); arming uses `ensure_editable(schedule_change=True)`, `ensure_future` and `ensure_can_prepare`; arming or disarming or changing the date clears the error columns; replace the `arm` SQL helper in tests written later with the API where convenient. Makes T018 pass.
- [X] T021 [P] [US2] Add the explicit consent UI in `frontend/src/components/PublicationCreate.tsx` (checkbox only shown when a date is set) and in `ScheduleForm` of `frontend/src/components/PublicationDetail.tsx` (checkbox initialised with the current value, dynamic button label, explanation text, both fields always sent), plus `Enable auto-publish` (confirmation dialog) / `Disable auto-publish` buttons for `scheduled` publications. Makes T019 pass.

**Checkpoint**: flujo P1 completo desde la interfaz: programar + armar → publicación automática.

---

## Phase 5: User Story 3 - Ventana segura tras apagados y reinicios (Priority: P1)

**Goal**: ejecución automática solo dentro de `[scheduled_at, scheduled_at + 10 min]`, también
al arrancar; fuera, la publicación sigue `SCHEDULED` con la condición derivada overdue
visible; la recuperación de la Feature 006 termina antes del primer ciclo.

**Independent Test**: con reloj falso y una publicación armada para las 18:00, arrancar la
app a:

- 17:55 → no se ejecuta al arrancar; se ejecuta cuando llega las 18:00;
- 18:03 → elegible: se ejecuta en el primer ciclo;
- 18:09 → elegible: se ejecuta en el primer ciclo;
- 18:10:00 exactas → elegible: se ejecuta en el primer ciclo;
- 18:11 → no se ejecuta; permanece `SCHEDULED` y `overdue == true` (la interfaz muestra
  `Missed automatic publishing window`).

### Tests for User Story 3 ⚠️

- [X] T022 [P] [US3] Write `backend/tests/test_scheduler_lifecycle.py` (real thread with injected `wait` and `FakeClock`; fail before T024):
  - startup order: with an attempt left `running` (via `run_sql`) and an armed due publication, the first tick runs only after `recover_interrupted_attempts` closed the old attempt (spy/ordering list); the interrupted publication stays `failed` and is never re-run;
  - restart at 17:55 (stop app, set clock, start app) → still armed, nothing on the first tick, starts once the clock reaches 18:00; restart at 18:03 / 18:09 / 18:10:00 exactly → eligible, starts on the first tick; restart at 18:11 → no attempt, `status == "scheduled"`, still armed, overdue (`auto_publish_state == "overdue"`);
  - clean stop: `stop()` returns within `stop_timeout` while waiting; an exception raised inside a tick (patched selection query) is logged by class name and the next tick still runs;
  - `create_app(..., scheduler_settings=SchedulerSettings(autostart=False))` never starts the thread.
- [X] T023 [P] [US3] Extend `backend/tests/test_scheduler_tick.py` and `backend/tests/test_auto_publish_consent.py` for the window: candidate exactly at `scheduled_at`, inside, exactly at `+10:00` (starts) and one microsecond later (does not); the window is re-evaluated at claim time: advance `FakeClock` past the window inside `FakePublisher.prepare` → no attempt, publication stays `scheduled` and overdue; `GET` of an armed overdue publication shows `status: "scheduled"`, `auto_publish_state: "overdue"` and `auto_publish_window_ends_at`; a disarmed past-date publication shows `disabled` (not overdue); disarming an overdue one → `disabled` (no longer overdue); rescheduling it to a future date with `auto_publish_enabled: true` → `waiting` with the new window.

### Implementation for User Story 3

- [X] T024 [US3] Startup and window guarantees in `backend/app/main.py`, `backend/app/scheduler.py` and `backend/app/publishing.py` (makes T022–T023 pass):
  - lifespan order exactly: (1) `run_migrations`; (2) `PublishContext`, `PublicationRunner` and `app.state.publishers` registered; (3) `recover_interrupted_attempts(session_factory)` returns (closes every `running` attempt / `publishing` publication); (4) `Scheduler` built and `start()`ed; the first `run_once()` runs right after `start()`;
  - T022 asserts it with an ordering list recorded by spies on `recover_interrupted_attempts` and `Scheduler.run_once`: no candidate is selected (and no `check`/`prepare` call happens) before recovery has returned;
  - the claim time is read again after the preflight: `start_publication` passes `clock` to `create_running_attempt`, which calls `clock()` right before the `UPDATE`; T023 proves it by advancing `FakeClock` past the window inside `FakePublisher.prepare` → no claim;
  - the candidate query only returns rows with `scheduled_at <= now` and `scheduled_at >= now - AUTO_PUBLISH_WINDOW`.
- [X] T025 [P] [US3] Show the window state in `frontend/src/components/PublicationDetail.tsx`: for an overdue publication (`status` `scheduled`, `auto_publish_state` `overdue`), `Missed automatic publishing window` + `Publish now or reschedule` (Publish now and the schedule form remain available) and the window end time; for `disabled` with a past date, only `Auto-publish disabled`. Add the cases to `frontend/src/components/PublicationDetail.test.tsx` first.

**Checkpoint**: todas las historias P1 completas.

---

## Phase 6: User Story 4 - Pausar y reanudar la automatización (Priority: P2)

**Goal**: interruptor global persistente; con pausa no hay inicios ni preflights automáticos;
`Publish now` y las subidas en curso no se ven afectados.

**Independent Test**: pausar, pasar la hora de una armada, comprobar que no hubo `check` ni
`prepare`; reiniciar → sigue pausada; reanudar dentro de la ventana → se ejecuta; fuera →
sigue `SCHEDULED` y overdue.

### Tests for User Story 4 ⚠️

- [X] T026 [P] [US4] Write `backend/tests/test_automation_api.py` (fail before T029): `GET /api/automation` after migration → `paused: false`, `running` reflects the thread (false with `autostart=False`), `check_interval_seconds: 30`, `window_minutes: 10`, `last_check_at` null then set after a tick; `PUT {"paused": true}` → persisted across app restart; idempotent; missing/invalid body → `422`; deleting the row via SQL → `GET` reports `paused: true` and `PUT` recreates it; `PUT {"paused": false}` calls `scheduler.wake()`.
- [X] T027 [P] [US4] Extend `backend/tests/test_scheduler_tick.py` for pause: paused → `run_once()` starts nothing and `FakePublisher.check/prepare` counters stay at 0; pause set **during** `prepare` (from inside `FakePublisher.prepare`) → claim rejected, no attempt, no error recorded; an upload `publishing` when pausing completes normally; `Publish now` while paused succeeds (`manual`); resume within the window → starts on the next tick; resume after the window → stays `scheduled` and overdue, nothing started, never a batch of old publications; `auto_publish_state = "paused"` for armed publications while paused.
- [X] T028 [P] [US4] Write `frontend/src/components/AutomationStatus.test.tsx`: shows `Automation running` (+ last check time) or `Automation paused`, the `Pause automation` / `Resume automation` button calls `setAutomationPaused` and refreshes, and always shows "AutoPublisher must be running to publish automatically."

### Implementation for User Story 4

- [X] T029 [US4] Implement `GET`/`PUT /api/automation` in the `router` of `backend/app/automation.py`: reads `is_paused`, `app.state.scheduler.running` and `last_check_at`; `PUT` uses `set_paused` and, when resuming, `scheduler.wake()`. Add the pause check at the start of `Scheduler.run_once()` (paused → return an empty report before selecting candidates). Makes T026–T027 pass.
- [X] T030 [US4] Create `frontend/src/components/AutomationStatus.tsx` (loads `getAutomation()`, shows state, last check, toggle and the "must be running" note) and render it at the top of `frontend/src/components/PublicationQueue.tsx`; when paused, armed publications show `Automation paused` in the detail. Makes T028 pass.

---

## Phase 7: User Story 5 - Ninguna ejecución duplicada (Priority: P2)

**Goal**: como máximo un intento por publicación ante ciclos repetidos, ciclos concurrentes,
varios workers o un `Publish now` simultáneo.

**Independent Test**: dos `run_once()` concurrentes y un `Publish now` simultáneo sobre la
misma publicación → exactamente un `PublicationAttempt` y una subida.

### Tests for User Story 5 ⚠️

- [X] T031 [P] [US5] Write `backend/tests/test_scheduler_concurrency.py` (fail if T007's guards are removed): two threads calling `run_once()` on the same `Scheduler` and on two `Scheduler` instances sharing the database, synchronised with a `threading.Barrier` inside `FakePublisher.prepare` → one attempt, one `upload` call; scheduler tick + `POST /publish` released together → exactly one attempt, the loser gets `409 publication_in_progress` (manual) or is silently skipped (scheduler); three consecutive ticks while the upload is blocked → one attempt; publications in `publishing`, `published`, `failed`, `cancelled` are never started; disarm, cancel or reschedule performed inside `prepare` → no attempt; the same flow with the YouTube simulator shows a single session start request.

### Implementation for User Story 5

- [X] T032 [US5] Atomic claim for `scheduled` executions in `backend/app/publishing.py` and `backend/app/scheduler.py` (makes T031 pass):
  - `create_running_attempt` performs the claim as **one transaction**: conditional `UPDATE publications` + `INSERT` of the `PublicationAttempt` with `trigger='scheduled'`, committed together; no commit between them;
  - the `UPDATE` carries every approved guard from `scheduled_claim_conditions(clock(), max_concurrent)`: `status='scheduled'`, `auto_publish_enabled=1`, `automation_paused=0`, window bounds, no `running` attempt for the publication, and fewer than `max_concurrent` running `scheduled` attempts (automatic slot available);
  - `rowcount != 1` → rollback and `publication_not_eligible`/`publication_in_progress`; `IntegrityError` on `uq_publication_attempts_running` → rollback and `publication_in_progress`; the scheduler treats both as "not claimed": no error recorded, no `runner.start`, no upload session;
  - `runner.start` is called only after the commit succeeded, so two concurrent cycles can never produce two attempts nor two executions; no in-memory lock is part of the guarantee.

---

## Phase 8: User Story 6 - Fallos de preflight a la hora programada (Priority: P2)

**Goal**: un preflight automático fallido no tiene efectos externos, deja `scheduled`, guarda
un motivo seguro y se re-comprueba como mucho cada 120 s (también tras reiniciar) solo
dentro de la ventana.

**Independent Test**: para cada causa de preflight, vencer una armada y comprobar sin
intento ni subida, motivo visible, re-comprobación limitada y fin al cerrar la ventana.

### Tests for User Story 6 ⚠️

- [X] T033 [P] [US6] Write `backend/tests/test_scheduler_preflight.py` (fail before T035):
  - with the YouTube simulator: inactive project, inactive account, connection `reconnect_required`, not connected, missing media file, invalid metadata (title > 100), incomplete YouTube options, publisher not registered (empty `publishers` map), temporary network error during credential refresh (`youtube_unavailable`), ambiguous previous attempt (`remote_check_required`) → publication stays `scheduled` and armed, no `PublicationAttempt`, no upload session request in the simulator, `auto_publish_error` with the existing code and message, `failed_at = clock()`;
  - `FakePublisher.prepare` raising `RuntimeError("secret ya29.x")` → stored as `internal_error` with the fixed message; logs contain the class name only, never the message;
  - throttle: ticks at +30 s, +60 s, +119 s do not call `prepare` again; +120 s does; restart the app (new `Scheduler`, same DB) 30 s after a failure → the first tick does **not** re-check; after the window ends → never selected again, error kept, status `scheduled` and overdue;
  - problem fixed within the window (e.g. reactivate the account) → next allowed check starts it and the error is cleared;
  - error cleared when rescheduling, disarming, or starting (manual or scheduled); a stale error write after a concurrent reschedule (reschedule from inside `prepare`) is not applied (conditional `UPDATE` on `scheduled_at`).
- [X] T034 [P] [US6] Extend `frontend/src/components/PublicationDetail.test.tsx`: an `auto_publish_error` is shown with its message and time ("Could not start automatically: …"), also together with `Missed automatic publishing window`; nothing is shown when `null`.

### Implementation for User Story 6

- [X] T035 [US6] Implement in `backend/app/automation.py` `record_auto_publish_error(session, publication_id, scheduled_at, code, message, now)` (conditional `UPDATE ... WHERE status='scheduled' AND auto_publish_enabled=1 AND scheduled_at=:scheduled_at`), and in `backend/app/scheduler.py`: add the retry condition to the candidate query (`auto_publish_failed_at IS NULL OR auto_publish_failed_at <= now - preflight_retry_interval`), catch `ConflictError`/`AppError`/`NotFoundError` (other codes) → record; any other `Exception` → record `internal_error` ("AutoPublisher could not start this publication automatically.") and log the class name; `WARNING` log once per failure with id + code. Makes T033 pass.
- [X] T036 [US6] Show `auto_publish_error` in `frontend/src/components/PublicationDetail.tsx`. Makes T034 pass.

---

## Phase 9: User Story 7 - Varias publicaciones vencen a la vez (Priority: P3)

**Goal**: orden determinista y como máximo 2 ejecuciones automáticas simultáneas, sin
pérdidas ni duplicados; los manuales no consumen slots.

**Independent Test**: 4 publicaciones armadas a la misma hora → orden por fecha e id,
nunca más de 2 intentos `running` `scheduled`, el resto en ciclos siguientes o, si su ventana termina, `SCHEDULED` y overdue.

### Tests for User Story 7 ⚠️

- [X] T037 [P] [US7] Extend `backend/tests/test_scheduler_tick.py` and `backend/tests/test_scheduler_concurrency.py` (fail before T038):
  - order: publications at 18:00 (ids 3 and 1) and 17:59 → start order 17:59, then id 1, then id 3 (`TickReport.started` and attempt `started_at`);
  - slots: 4 due with uploads blocked → first tick starts 2, `skipped_capacity` has the other 2 and **no** `prepare` was called for them; releasing one upload (→ `published`) frees a slot and the next tick starts the next; a `failed` upload also frees it; 2 manual uploads running do not consume slots;
  - with 2 automatic uploads running, `Publish now` still starts a manual one;
  - atomic limit: two `Scheduler` instances with 4 due candidates and a `Barrier` in `prepare` so both pass the pre-check and preflight simultaneously → never more than 2 running `scheduled` attempts; the loser is skipped without recording an error;
  - waiting beyond the window: due publications blocked by capacity until after `+10 min` → never started, still `scheduled`, overdue in `GET`.

### Implementation for User Story 7

- [X] T038 [US7] Add the slot pre-check to `Scheduler.run_once()` in `backend/app/scheduler.py`: count running attempts with `trigger='scheduled'`; free = `max_concurrent - count`; if `free <= 0` skip all (no preflight); otherwise try candidates in order until `free` starts succeeded, recording the rest in `skipped_capacity`. The final guarantee stays in the claim `UPDATE` (T006/T007). Makes T037 pass.

---

## Phase 10: User Story 8 - Ver el estado de la automatización en la Queue (Priority: P3)

**Goal**: la Queue muestra por publicación programada fecha, armado, espera, pausa, overdue y
último fallo. El refresco automático ya existe desde US1 (T017); aquí se completan etiquetas
y UX.

**Independent Test**: Queue con publicaciones en cada `auto_publish_state`, pausada y en
marcha; cada fila muestra la etiqueta correcta y la cabecera muestra `AutomationStatus`.

### Tests for User Story 8 ⚠️

- [X] T039 [P] [US8] Write `frontend/src/components/AutoPublishBadge.test.tsx` and extend `frontend/src/components/PublicationQueue.test.tsx`: badge per derived `auto_publish_state` of `scheduled` publications (`Auto-publish enabled` + "Waiting for its time" / "Starting soon", `Auto-publish disabled` even with a past date, `Automation paused`, overdue → `Missed automatic publishing window` + `Publish now or reschedule`, plus the short error message); scheduled date shown in local time; labels change after a refresh from the US1 polling (e.g. `waiting` → `due` → `overdue`); `AutomationStatus` is rendered in the Queue header.
- [X] T040 [P] [US8] Extend `backend/tests/test_publications_queue.py`: the list includes the new fields for every row, reads the pause flag once, and keeps the existing order.

### Implementation for User Story 8

- [X] T041 [US8] Create `frontend/src/components/AutoPublishBadge.tsx` and use it in `frontend/src/components/PublicationQueue.tsx` rows and in `frontend/src/components/PublicationDetail.tsx` (reusing the polling added in T017, without changing it). Makes T039–T040 pass.

---

## Phase 11: Polish & Cross-Cutting Concerns

- [X] T042 [P] Write `backend/tests/test_scheduler_secrets.py`: a full automatic execution with the YouTube simulator (`FAKE_UPLOAD_ID`, fake tokens) plus a failed automatic preflight → SQLite `.dump`, every JSON response (`/api/automation`, publications, attempts) and logs captured at `DEBUG` contain no access/refresh token, `Authorization`/`Bearer`, `upload_id` or video ID in logs; `auto_publish_error_message` contains only existing safe messages.
- [X] T043 [P] Extend `frontend/src/storage-safety.test.tsx` (no automation data or errors written to `localStorage`/`sessionStorage`) and `frontend/src/utils.test.ts` (local → UTC conversion with `TZ=Europe/Madrid` around the October DST change: repeated hour and skipped hour in March).
- [X] T044 [P] Update `README.md` with an "Automatic publishing" section: AutoPublisher must be running; explicit consent (`Schedule & enable auto-publish`) and pre-existing scheduled publications stay disabled after upgrading; 10-minute window and `Missed automatic publishing window`; `Pause automation` / `Resume automation`; at most 2 automatic uploads at once; no automatic retries after a failure; no cron/system service.
- [X] T045 Run the full quality gates: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`; also run the full automated suites without Internet to confirm SC-013: use `unshare -rn uv run pytest` (and `unshare -rn npm test`) when `unshare` is available and allowed; otherwise run them with the network disconnected or blocked by another explicit means (e.g. disabling the network interface or a firewall rule) and note which method was used. The criterion is that no automated test depends on Internet. Report any failure.
- [X] T046 Manual validation following [quickstart.md](quickstart.md) §3–§6 with real YouTube (`private`, `Notify subscribers = No`); record observed delay to `Publishing` and the pause/overdue/migration results for the PR, without video IDs or URLs.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; bloquea todas las historias.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de US1 (sus tests end-to-end usan `run_once`, y T019/T021
  editan `PublicationDetail.test.tsx`/`PublicationDetail.tsx`, que también toca T015).
- **US3 (Phase 5)**: depende de US1 (ciclo) y de US2 para los casos de desarmar/reprogramar.
- **US4 (Phase 6)**: depende de US3 (comparten `scheduler.py` y
  `test_scheduler_tick.py`).
- **US5 (Phase 7)**: depende de US4 (comparte `scheduler.py`) y de US2 para
  desarmar/reprogramar durante `prepare`.
- **US6 (Phase 8)**: depende de US5 (comparten `scheduler.py`); usa US2 para la limpieza al
  reprogramar/desarmar.
- **US7 (Phase 9)**: depende de US6 (comparten `scheduler.py`, `test_scheduler_tick.py` y
  `test_scheduler_concurrency.py`).
- **US8 (Phase 10)**: depende de US4 (`AutomationStatus`) y de los campos derivados de
  Foundational; muestra el error de US6 si existe.
- **Polish (Phase 11)**: depende de todas las historias deseadas.

### Within Each Phase

- Tests primero (deben fallar), después la implementación.
- Backend antes que frontend cuando el frontend consume un campo o endpoint nuevo.
- T005 → T006 → T007 → T008 (both edit `publishing.py`) → T009 → T010 → T011; T012 y T013 en paralelo con T006–T011.

### Parallel Opportunities

- Foundational: T002, T003, T004 en paralelo; T012 y T013 en paralelo con la implementación.
- Dentro de cada historia: las tareas marcadas [P] no comparten archivo con ninguna otra
  tarea de su fase y pueden ejecutarse a la vez (p. ej. tests de backend y de frontend, o la
  interfaz mientras se implementa el backend).
- **Entre historias no hay paralelismo de backend**: US1, US3, US4, US5, US6 y US7 editan
  `backend/app/scheduler.py` y comparten `test_scheduler_tick.py` /
  `test_scheduler_concurrency.py`; US1, US2, US3, US4, US6 y US8 editan
  `PublicationDetail.tsx` y su test, y US1, US4 y US8 editan `PublicationQueue.tsx` y su
  test. Las historias se ejecutan en orden de prioridad
  (US1 → US8).

---

## Parallel Example: Foundational

```bash
Task: "T002 Extend backend/tests/test_migrations.py for 0006"
Task: "T003 Write backend/tests/test_automation_state.py"
Task: "T004 Extend the architecture test in backend/tests/test_publications_states.py"
Task: "T013 Update frontend/src/types.ts, api.ts and test-fake-api.ts"
```

## Parallel Example: User Story 2

```bash
Task: "T018 Write backend/tests/test_auto_publish_consent.py"
Task: "T019 Extend PublicationCreate.test.tsx and PublicationDetail.test.tsx"
```

---

## Implementation Strategy

### MVP First (User Stories 1–3, all P1)

1. Phase 1 + Phase 2.
2. US1: el scheduler inicia publicaciones armadas mediante `start_publication`.
3. US2: armado explícito desde la API y la interfaz; nada antiguo armado.
4. US3: ventana de 10 minutos, arranque seguro y condición overdue (sin estado nuevo).
5. **Parar y validar**: tests en verde; quickstart §3 y §5 con YouTube real.

### Incremental Delivery

1. P1 (US1–US3) → publicación automática segura.
2. US4 (pausa) + US5 (duplicados) + US6 (fallos de preflight) → robustez (P2).
3. US7 (varias a la vez) + US8 (Queue) → P3.
4. Polish → secretos, README, quality gates, validación real.

### Notes

- Commits pequeños en inglés, por tarea o grupo lógico, solo cuando el usuario lo pida.
- No ampliar el alcance: nada de retries entre intentos, cron/systemd/cloud, Calendar,
  Dashboard, recurrencias, notificaciones ni otras plataformas.
