---

description: "Task list for real manual YouTube video publishing"
---

# Tasks: Publicación manual real de vídeos en YouTube

**Input**: Design documents from `specs/006-youtube-manual-publishing/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-056, SC-013). Se usan un simulador de subida
resumible sobre `httpx2.MockTransport` y el almacén de credenciales en memoria de la
Feature 005. Ningún test sube vídeos reales, usa Internet ni el llavero del sistema. En cada
fase los tests se escriben primero y deben fallar antes de implementar; ninguna
comprobación se implementa antes de que exista un test que la cubra.

**Organization**: tareas agrupadas por historia de usuario (US1–US7 de la spec). Código,
comentarios, mensajes de API y UI, README y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes).
- **[Story]**: historia de usuario a la que pertenece (US1–US7).

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`.
- Frontend: `frontend/src/`, `frontend/src/components/`.
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- **Secretos**: access/refresh tokens, cabeceras `Authorization`, la URI de sesión
  resumible y su `upload_id` **nunca** aparecen en SQLite, logs (ni en mensajes de
  excepción), respuestas JSON ni el frontend. La URI de sesión solo existe en variables
  locales del hilo de subida. El código de subida nunca registra excepciones con `exc_info`
  ni su `str()`: solo el nombre de la clase y los ids internos.
- **Video ID**: nunca se escribe en logs. Solo se persiste en `publication_attempts` de un
  intento `succeeded` (research §7).
- **Mensajes de error**: fijos por código (research §6); nunca texto de Google. De las
  respuestas de error solo se lee `error.errors[0].reason`.
- **Write-ahead** (research §5): `stage = 'final_chunk'` se escribe **y se confirma con
  commit** antes de enviar el fragmento que contiene el último byte. Si el commit falla, ese
  fragmento no se envía. Al recibir el video ID, el resultado remoto, el intento
  `succeeded` y la publicación `published` se persisten inmediatamente en una única
  transacción.
- **Nunca resubir automáticamente**: ni tras un resultado ambiguo ni tras un reinicio. Las
  reanudaciones dentro de la misma sesión resumible pertenecen al mismo intento.
- **Sin ejecución por fecha**: ningún código reacciona al paso de `scheduled_at`.
- **Núcleo genérico** (Constitution III, research §2):
  - `publishing.py` y `publications.py` no importan `app.youtube_*`, `app.credential_store`,
    `httpx`/`httpx2` ni `keyring`; `Publication` no tiene campos de YouTube;
  - `PublishContext` solo contiene `session_factory`, `storage` y `settings:
    PublishingSettings` (núcleo: `sleep`, esperas de reintento de persistencia, intervalo de
    progreso, timeout de parada);
  - todo lo específico de YouTube (gateway, almacén de credenciales,
    `YouTubeUploadSettings`) lo recibe `YouTubePublisher` en su constructor;
  - `main.py` es la raíz de composición: construye el publisher y lo registra en
    `app.state.publishers[Platform.YOUTUBE]`; el núcleo solo usa el protocolo `Publisher`.
- **Errores**: formato existente `{"error": {"code", "message", "fields"}}` con los códigos
  de [contracts/api.md](contracts/api.md).
- **Endpoints síncronos** (`def`) como el resto del proyecto. El hilo de subida usa sesiones
  de base de datos cortas propias (`ctx.session_factory`), nunca la de la petición.
- **Tests deterministas**: ningún test depende de esperas reales, timeouts accidentales ni
  de que un hilo daemon termine solo; los bloqueos del simulador se controlan con
  `threading.Event` y las esperas con funciones `sleep` inyectadas.
- **Catálogos duplicados** backend (`StrEnum`) ↔ frontend (`types.ts`), con un comentario en
  cada lado que apunte al otro: `PublicationStatus`, estados y fases del intento,
  privacidad de YouTube.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: línea base. No hay dependencias nuevas (plan, Technical Context).

- [X] T001 Verify the baseline on branch `006-youtube-manual-publishing`: run `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`. All must pass before any change; record any pre-existing failure instead of fixing it silently.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: estados nuevos, migración, modelo de intentos y opciones, núcleo de ejecución
genérico, simulador de YouTube, reglas de edición por estado, redacción de logs y
tipos/cliente del frontend.

**⚠️ CRITICAL**: no se puede empezar ninguna historia hasta completar esta fase.

**Orden interno**: primero los tests que no necesitan abstracciones nuevas (T002–T004);
después la implementación (T005–T012); después el soporte de tests que usa las
abstracciones recién creadas (T013); por último el resto de la implementación (T014–T016).

### Tests fundacionales (escribir primero)

- [X] T002 [P] Extend `backend/tests/fakes.py` with a **resumable upload simulator** inside `FakeGoogle` (same `httpx2.MockTransport` handler). It only depends on `httpx2` and the existing fakes, not on any new app module:
  - **Session start**: `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status&notifySubscribers=…` records the JSON body (`snippet`, `status`), the query params and the headers `X-Upload-Content-Length` / `X-Upload-Content-Type`, and returns `200` with `Location: https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=<FAKE_UPLOAD_ID>`.
  - **Chunks**: `PUT` on that URI with `Content-Range: bytes S-E/T` appends the received bytes (consuming the streamed body), returns `308` with `Range: bytes=0-N` until complete and then `200` with a video resource (`id`, `status.privacyStatus`, `status.uploadStatus`); the returned privacy is configurable to differ from the requested one.
  - **Status query**: empty `PUT` with `Content-Range: bytes */T` returns `308` + `Range` (or no `Range` when nothing was received) or the final `200` if the upload already completed.
  - **`videos.list`**: `GET https://www.googleapis.com/youtube/v3/videos?part=status,processingDetails&id=…` returns `status` and `processingDetails` for created videos; can be programmed to fail.
  - **Programmable fault queue** applied per request: transport error (raise `httpx2.ConnectError` / `ReadTimeout`, optionally after the server stored the bytes), `500`/`502`/`503`/`504`, `429`, `503` with `Retry-After` (seconds or HTTP date), `401`, `403` with reason (`quotaExceeded`, `forbidden`, `rateLimitExceeded`), `400` with reason (`uploadLimitExceeded`, `invalidTitle`), `404` on the session URI, `308` with a shorter `Range` after the last chunk, a final `200` without `id` or with an invalid `id`.
  - **Deterministic blocking**: `block_uploads(at="session_start" | "chunk" | "last_chunk")` makes the matching request wait on a `threading.Event` until the test calls `release()`; `wait_until_blocked(timeout)` lets the test know the request has arrived. Used by the asynchronous-response and shutdown tests.
  - **Hooks**: an optional callback invoked before handling each upload request (used by tests to inspect the DB `stage` at that moment).
  - **Recording**: list of requests (method, URL, headers, body size), bytes received per session, `videos_created` list; a request to an unexpected URL fails the test.
  - **Constants**: distinctive `FAKE_UPLOAD_ID` and `FAKE_VIDEO_ID` (11 chars `[A-Za-z0-9_-]`) reused by leak tests.
- [X] T003 [P] Extend `backend/tests/test_migrations.py` (fail before T006):
  - upgrading a database populated at `0004` (project, accounts, contents, publications in `unscheduled`, `scheduled` and `cancelled`, a YouTube connection) to `0005` keeps every row, sets `published_at = NULL` and creates `publication_attempts` and `youtube_publication_options`;
  - `publications` accepts the new statuses; `published` requires `published_at` and other statuses reject it (`ck_publications_published_at_matches_status`); `publishing`/`published`/`failed` accept any `scheduled_at`;
  - the active-duplicates index now allows a `published` row and a new `unscheduled` row for the same content + account, but rejects two rows among `unscheduled`/`scheduled`/`publishing`/`failed`;
  - `publication_attempts`: a second `running` attempt for the same publication fails (`uq_publication_attempts_running`); invalid `status`/`stage`, `finished_at` inconsistent with `status`, `error_code` inconsistent with `status`, and `bytes_sent > total_bytes` fail their `CHECK`s;
  - `youtube_publication_options`: invalid `privacy_status` fails; two rows for the same publication fail;
  - constraint and index names are exactly those of [data-model.md](data-model.md); the existing models-vs-migrations drift test passes.
- [X] T004 [P] Write `backend/tests/test_publications_states.py` (fail before T014). States are prepared with the existing `run_sql` helper (no upload, no new helpers needed):
  - `PATCH /api/publications/{id}` in `publishing` or `published` → `409 publication_not_editable` (date, overrides); in `failed`, overrides are accepted and `scheduled_at` changes → `409 publication_not_editable`;
  - `POST .../cancel` in `publishing`/`published` → `409 publication_not_editable`; in `failed` → `cancelled`;
  - creating a publication for content + account with an existing `publishing` or `failed` one → `409 duplicate`; with a `published` one → `201`; `reactivate` follows the same rule;
  - `GET /api/publications/{id}` includes `published_at`, `latest_attempt` (`null` without attempts) and `attempt_count`;
  - **architecture of the generic core** (via `ast` over the module sources): `app.publishing` and `app.publications` import nothing from `app.youtube_*`, `app.credential_store`, `httpx`, `httpx2` or `keyring`; the fields of `app.publishing.PublishContext` are exactly `session_factory`, `storage` and `settings`, and `PublishingSettings` is defined in `app.publishing`; `app.youtube_upload` is the only module that defines `YouTubeUploadSettings`.

### Implementación fundacional

- [X] T005 Extend `backend/app/errors.py`: add to `ConflictCode` `publication_not_eligible`, `publication_in_progress`, `publication_not_editable`, `content_not_video`, `invalid_metadata`, `youtube_options_incomplete` and `remote_check_required`. Keep existing behaviour.
- [X] T006 Update `backend/app/models.py` and add the migration:
  - `PublicationStatus` + `PUBLISHING = "publishing"`, `PUBLISHED = "published"`, `FAILED = "failed"`; `Publication.published_at` (`UTCDateTime`, nullable); recreate `status_valid` and `status_matches_schedule`, add `published_at_matches_status`, change the `uq_publications_active_content_account` condition to `status NOT IN ('cancelled', 'published')` ([data-model.md §1](data-model.md)).
  - New `AttemptStatus` (`running`, `succeeded`, `failed`), `AttemptStage` (`preparing`, `uploading`, `final_chunk`, `done`) and model `PublicationAttempt` with every column, `CHECK`, the partial unique index `uq_publication_attempts_running` and `ix_publication_attempts_publication_id_started_at` ([data-model.md §2](data-model.md)).
  - New `YouTubePrivacy` (`private`, `unlisted`, `public`) and model `YouTubePublicationOptions` ([data-model.md §3](data-model.md)); no relationship from `Publication`.
  - `backend/migrations/versions/0005_publication_execution.py` with `down_revision = "0004"`, following [data-model.md §6](data-model.md) (`batch_alter_table` for `publications`, then drop/recreate the partial index), with exactly the names the naming convention produces. Makes T003 pass.
- [X] T007 Add schemas in `backend/app/schemas.py`:
  - `PublicationAttemptErrorRead` (`code`, `message`); `PublicationAttemptRead` with every field of [contracts/api.md](contracts/api.md) (`progress` computed, `requires_manual_review` computed, `external_id`/`external_url`, `submitted`, `details`, `warnings`);
  - `PublicationRead` + `published_at`, `latest_attempt: PublicationAttemptRead | None`, `attempt_count: int`; `status` accepts the new values;
  - `PublishRequest` (`confirm_remote_checked: bool = False`, `extra="forbid"`);
  - `PublishProblemRead` (`code`, `message`, `field: str | None`), `PublishSummaryItemRead` (`label`, `value`), `PublishCheckRead` (`eligible`, `problems`, `requires_remote_check`, `summary`, `scheduled_at`);
  - `YouTubePublicationOptionsRead` (`privacy_status`, `made_for_kids`, `contains_synthetic_media`, `notify_subscribers`, `complete`, `editable`) and `YouTubePublicationOptionsWrite` (all four fields required, nullable booleans for the two declarations, `extra="forbid"`).
  Depends on T006.
- [X] T008 [P] Add `get_video_status(access_token, video_id) -> dict[str, str]` to `GoogleGateway` in `backend/app/youtube_gateway.py`: `GET https://www.googleapis.com/youtube/v3/videos?part=status,processingDetails&id=<id>` with the `Authorization` header; returns only the whitelisted keys `privacy_status`, `upload_status`, `processing_status` that are present; any failure raises the existing `GoogleError` subclasses. Add its tests to `backend/tests/test_youtube_gateway.py` first (they must fail before the method exists).
- [X] T009 Create `backend/app/publishing.py` with the generic contracts. It imports only `app.models`, `app.schemas`, `app.errors`, `app.db`, `app.storage` and the standard library:
  - `PublishingSettings` (frozen dataclass, platform-independent): `sleep: Callable[[float], None] = time.sleep`, `persist_retry_waits: tuple[float, ...] = (0.5, 1.0, 2.0)`, `progress_interval: float = 1.0`, `stop_timeout: float = 5.0`;
  - `PublishContext` (frozen dataclass): `session_factory`, `storage: MediaStorage`, `settings: PublishingSettings` — nothing platform-specific;
  - `PublishProblem(code, message, field=None)`, `PublishCheck(problems, summary)`, `PreparedPublication` (`publication_id`, `file_path`, `total_bytes`, `submitted: dict`, `payload: object` opaque to the core), `PublishOutcome(external_id, external_url, details, warnings)`, `PublishFailure(Exception)` with `code`, `message`, `determined`;
  - `ProgressReporter` protocol: `report_bytes(n)`, `enter_final_chunk() -> bool`, `leave_final_chunk()`, `should_stop() -> bool`;
  - `Publisher` protocol: `check(session, publication, ctx) -> PublishCheck`, `prepare(session, publication, ctx) -> PreparedPublication`, `upload(prepared, reporter, ctx) -> PublishOutcome`, `refresh_details(prepared, outcome, ctx) -> PublishOutcome` (best effort);
  - `get_publishers(request) -> dict[Platform, Publisher]` reading `request.app.state.publishers`.
- [X] T010 Implement attempt persistence helpers in `backend/app/publishing.py`, each in its own short session from `ctx.session_factory`, using only `PublishingSettings` (no platform type is imported or received):
  - `create_running_attempt(session, publication, prepared, platform) -> int`: conditional `UPDATE publications SET status='publishing' … WHERE id=:id AND status IN ('unscheduled','scheduled','failed')`; `rowcount != 1` → `ConflictError("publication_in_progress")`; `INSERT` attempt `running`/`preparing` with `submitted`, `total_bytes`, `bytes_sent=0`, `platform`; `IntegrityError` → rollback and `publication_in_progress` (research §8);
  - `report_progress(ctx, attempt_id, bytes_sent)` (the reporter throttles it with `settings.progress_interval` and also calls it on every confirmed `308`), `set_stage(ctx, attempt_id, stage) -> bool` (returns `False` if the commit fails);
  - `persist_success(ctx, attempt_id, outcome)`: one transaction — attempt `succeeded`, `stage='done'`, `finished_at`, `outcome_determined=True`, `external_id`, `external_url`, `details`, `warnings`; publication `published` + `published_at`; retried with `settings.persist_retry_waits` through `settings.sleep`;
  - `persist_failure(ctx, attempt_id, code, message, determined)`: attempt `failed` + publication `failed`, same retries; never stores a video ID;
  - `recover_interrupted_attempts(session_factory)`: every `running` attempt → `failed`, `interrupted`, `outcome_determined = (stage != 'final_chunk')`, publication `failed` (research §9);
  - `requires_remote_check(session, content_id, account_id) -> bool`, `latest_attempt(session, publication_id)` and `attempt_counts(session, publication_ids)`.
- [X] T011 Implement `PublicationRunner(ctx: PublishContext)` in `backend/app/publishing.py`:
  - `start(attempt_id, prepared, publisher)`: registers the attempt as live, then starts a daemon `threading.Thread` running `_run`; if the thread cannot start, `persist_failure(..., "internal_error", determined=True)`;
  - `_run`: builds the reporter (stage, throttled progress, `should_stop` from `stop_event`), calls `publisher.upload(prepared, reporter, ctx)`; on success → `persist_success`, then `publisher.refresh_details` and an update of `details`/`warnings` (failures ignored); if `persist_success` fails → `persist_failure("result_not_saved", determined=False)` without video ID, and a log `ERROR` with only internal ids; on `PublishFailure` → `persist_failure(code, message, determined)`; on any other exception → `internal_error`, `determined = stage != 'final_chunk'`, log with class name only;
  - `stop()`: sets `stop_event` and joins live threads up to `settings.stop_timeout`; `wait_idle(timeout)` for tests; `is_live(attempt_id)`.
- [X] T012 Wire the app in `backend/app/main.py` (composition root): `create_app(..., publishing_settings: PublishingSettings | None = None, youtube_upload_settings: YouTubeUploadSettings | None = None)`. In `lifespan`, after `run_migrations` and before `yield`: `recover_interrupted_attempts(session_factory)`; `app.state.publish_context = PublishContext(session_factory, storage, publishing_settings or PublishingSettings())`; `app.state.publication_runner = PublicationRunner(...)`; `app.state.publishers = {}` (the YouTube publisher is constructed with its own gateway, credential store and upload settings and registered in T024); `runner.stop()` on shutdown; `include_router(publishing.router)`. Create `backend/app/youtube_upload.py` with `YouTubeUploadSettings` (frozen dataclass: `chunk_size=8 MiB`, `slice_size=256 KiB`, `max_consecutive_failures=6`, `max_backoff=32.0`, `max_retry_wait=60.0`, `sleep=time.sleep`) — the protocol itself comes in T023.

### Soporte de tests (tras existir las abstracciones de T009–T012)

- [X] T013 Extend `backend/tests/conftest.py` (written now because it needs `PublishingSettings`, `YouTubeUploadSettings` and `PublicationRunner` from T009–T012):
  - **Fixture `publishing_client`**: like `youtube_client`, with `create_app(..., publishing_settings=PublishingSettings(sleep=recorded_sleeps.append), youtube_upload_settings=YouTubeUploadSettings(chunk_size=256 * 1024, slice_size=64 * 1024, sleep=recorded_sleeps.append))` so no test really waits; expose `recorded_sleeps`.
  - **Helpers**:
    - `setup_publishable(client, fake_google, db_path, *, size=700_000, media_type="video", scheduled_at=None)`: active project, active YouTube account connected via `connect_youtube`, imported video content (`make_mp4` with enough payload) with title/description/hashtags, one publication; returns ids;
    - `set_youtube_options(client, publication_id, **overrides)`: `PUT .../youtube-options` with complete defaults (`private`, `made_for_kids=False`, `contains_synthetic_media=False`, `notify_subscribers=False`);
    - `publish_and_wait(client, publication_id, **body)`: `POST .../publish`, then `app.state.publication_runner.wait_idle(timeout=10)` and returns the final publication JSON;
    - `attempt_rows(db_path)`: raw rows of `publication_attempts`.

### Implementación fundacional (continuación)

- [X] T014 Update `backend/app/publications.py` for the new states (makes T004 pass):
  - `ensure_editable(publication, *, schedule_change: bool)` per the matrix of [research.md §13](research.md): `publishing`/`published` → `publication_not_editable`; `failed` + date change → `publication_not_editable`; `cancelled` keeps `publication_cancelled`; reused by `update_publication`, `cancel_publication` and later by the YouTube options;
  - `find_active` uses `status NOT IN (cancelled, published)`;
  - Queue order per [research.md §14](research.md): `publishing`, `failed`, `scheduled` (date ↑), `unscheduled` (created ↑), `published` (`published_at` ↓), `cancelled` (`updated_at` ↓), then `id`;
  - `publication_to_read` fills `published_at`, `latest_attempt` and `attempt_count` (one aggregate query for the list, one query for the detail), using the helpers of T010.
- [X] T015 [P] Log redaction in `backend/app/youtube_connections.py`: first add a unit test in `backend/tests/test_publish_secrets.py` that emits a record with a fake session URL through the `httpx`/`httpx2`/`httpcore` loggers and asserts the `upload_id` value is gone (must fail); then add `RedactUploadSessionUrl(logging.Filter)` that replaces any `upload_id=<value>` in `record.msg` and `record.args` with `upload_id=[redacted]`, installed in `install_log_redaction()` on those loggers (verify the actual logger name used by `httpx2` and keep only the real ones).
- [X] T016 [P] Frontend foundations:
  - **`frontend/src/types.ts`**: `PublicationStatus` + `publishing`, `published`, `failed` with labels `Publishing`, `Published`, `Failed`; `AttemptStatus`, `AttemptStage`, `PublicationAttempt`, `PublishCheck`, `PublishProblem`, `YouTubePrivacy` (+ labels), `YouTubePublicationOptions`; `Publication` + `published_at`, `latest_attempt`, `attempt_count`. Sync comments to backend.
  - **`frontend/src/api.ts`**: `getYouTubeOptions(id)`, `saveYouTubeOptions(id, body)`, `getPublishCheck(id)`, `publishNow(id, confirmRemoteChecked)`, `listAttempts(id)`, with the existing `request` helper.
  - **`frontend/src/test-fake-api.ts`**: in-memory YouTube options per publication, a configurable `PublishCheck`, a `publishNow` that moves the publication to `publishing` and lets tests advance the attempt (`progress`, `succeed(videoUrl, privacy)`, `fail(code, message, determined)`), attempts list, and a call log.
  - **`frontend/src/index.css`**: badges `status-publishing`, `status-published`, `status-failed`, progress bar, warning and manual-review notices.

**Checkpoint**: migración aplicada, estados nuevos visibles en la API, reglas de edición
activas, núcleo genérico (contexto, runner, recuperación) cableado sin dependencias de
YouTube; las historias pueden empezar.

---

## Phase 3: User Story 1 - Publicar ahora un vídeo en YouTube (Priority: P1) 🎯 MVP

**Goal**: `Publish now` con confirmación y preflight completo sube de verdad el vídeo con
el protocolo resumible y deja la publicación `PUBLISHED` con su enlace.

**Independent Test**: con el simulador, una publicación `unscheduled` de un vídeo con
opciones completas pasa por `publishing` (progreso visible) a `published` con video ID y
`Open on YouTube`; existe un intento `succeeded`; el archivo local no cambia; cualquier
condición de preflight no cumplida se rechaza sin contactar con el endpoint de subida.

### Tests for User Story 1 ⚠️

Incluyen las pruebas exhaustivas del preflight (T019–T020): el preflight forma parte de
`Publish now` (US1, escenario 4) y se implementa en T022, así que sus tests deben existir
antes. US3 conserva la paridad con `publish-check` y la interfaz de problemas.

- [X] T017 [P] [US1] Write the end-to-end publishing tests (fail before T022–T025):
  - **`backend/tests/test_publish_upload.py`** (happy path):
    - `POST /api/publications/{id}/publish` → `202` with `status = "publishing"` and `latest_attempt` `running`/`preparing`; after `wait_idle`, `published`, `published_at` set, `latest_attempt` `succeeded`/`done`, `external_id = FAKE_VIDEO_ID`, `external_url = "https://www.youtube.com/watch?v=" + FAKE_VIDEO_ID`, `outcome_determined = true`, `attempt_count = 1`;
    - session start request: `part=snippet,status`, `notifySubscribers=false`, `X-Upload-Content-Length` = file size, `X-Upload-Content-Type` = `video/mp4`, body `snippet.title`/`snippet.description` (hashtags appended), no `snippet.tags`, no `categoryId`, no `status.publishAt`, `status.privacyStatus`, `status.selfDeclaredMadeForKids`, `status.containsSyntheticMedia` as configured;
    - chunks: `Content-Range` of each `PUT` correct, every chunk ≤ `chunk_size`, chunk sizes multiple of 256 KiB except the last, the bytes received by the fake are identical to the file;
    - progress: `bytes_sent` written during the upload (inspect from the fake's hook) and equal to `total_bytes` at the end;
    - **write-ahead order**: through the fake's hook, when the request containing the last byte arrives the DB row already has `stage = 'final_chunk'` committed; no earlier request sees `final_chunk`;
    - the file's SHA-256 and mtime are unchanged; no file is created under the media `tmp` dir;
    - `notify_subscribers=True` → `notifySubscribers=true` in the query;
    - `submitted` contains exactly the whitelisted keys of [data-model.md §2.1](data-model.md); `details` contains `privacy_status` (and `processing_status` after the light check);
    - restarting the app (new `TestClient` on the same DB and store) keeps the publication `published` with the same attempt, video ID and URL;
    - **real privacy differs (C4)**: options request `public`; the fake accepts the upload but returns `status.privacyStatus = "private"` (in the upload response and in `videos.list`) → publication `published`, attempt `succeeded`; reading the persisted row (`attempt_rows`) gives `details.privacy_status = "private"` and `warnings` containing an entry with code `privacy_differs` and the adapter's fixed message; the warning message contains no text from the fake's response body;
    - **light check fails (C5)**: the upload completes with a valid video ID, then `videos.list` fails (one run with `503`, one with a transport error) → publication stays `published`, attempt stays `succeeded` (never `failed`), `external_id`/`external_url` set, and `details` keeps the values from the upload response itself (`privacy_status`, `upload_status`); the failure is not surfaced as an error.
  - **`backend/tests/test_publish_service.py`**:
    - **FR-013 (reusable service)**: inside the running app, open a session with `app.state.publish_context.session_factory` and call `start_publication(session, publication_id, confirm_remote_checked=False, ctx=app.state.publish_context, runner=app.state.publication_runner, publishers=app.state.publishers)` directly — no HTTP request, no FastAPI dependency; assert it returns the attempt id, the publication is `publishing`, and after `runner.wait_idle` it is `published` with one attempt. Also assert the function signature has no `Request`/FastAPI parameter;
    - **SC-002 (asynchronous response)**: `fake_google.block_uploads(at="chunk")`; `POST .../publish` returns `202` with `status = "publishing"` while `fake_google.wait_until_blocked()` confirms the upload is still in progress and the publication is still `publishing` in the DB; then `release()` and `wait_idle` → `published`.
- [X] T018 [P] [US1] Write `backend/tests/test_youtube_upload.py` (unit tests of the protocol, fail before T023): against the fake, `ResumableUpload` reads the file in `slice_size` pieces (assert via a wrapped file object that no `read` exceeds `slice_size`), follows `308` `Range` (including a `308` without `Range` → restart from 0), returns the video resource on `200`/`201`, and calls `enter_final_chunk()` exactly before the last chunk; if `enter_final_chunk()` returns `False`, the last chunk is never sent and a determined `PublishFailure("internal_error")` is raised.
- [X] T019 [P] [US1] Write `backend/tests/test_publish_preflight.py` (exhaustive preflight, fail before T022/T025), asserting for every case the HTTP code + error code, unchanged publication status, zero attempts and zero requests to `/upload/youtube/v3/videos`: project inactive; account inactive; non-YouTube account (`platform_not_supported`); image content (`content_not_video`); missing file and file with a different size (`media_unavailable`); title empty / 101 characters / containing `<` (`invalid_metadata`, field `title`); description over 5000 bytes with multibyte characters and with `>` (field `description`); options incomplete (`youtube_options_incomplete`); OAuth client file missing (`503 oauth_not_configured`); `not_connected`; `reconnect_required`; refresh `invalid_grant` (→ `reconnect_required`, connection marked); credential store unavailable (`503`); Google unreachable (`503 youtube_unavailable`, connection unchanged); `channels.list` returning another channel or two channels (`reconnect_required`, connection marked, nothing uploaded); state `publishing` (`publication_in_progress`), `published` and `cancelled` (`publication_not_eligible`); `scheduled` with a past date is eligible; `failed` whose last attempt was determined is eligible (FR-014; the ambiguous case is covered in T046).
- [X] T020 [P] [US1] Write `backend/tests/test_youtube_metadata.py` (pure unit tests, fail before T022): `build_description` for description + hashtags, hashtags only (no leading blank line), description only, neither; 100 vs 101 characters (counting code points, e.g. emoji); 5000 vs 5001 bytes with multibyte text; `<` and `>` in title and description; hashtags never appear in a `tags` field.
- [X] T021 [P] [US1] Write `frontend/src/components/PublicationDetail.test.tsx` cases for publishing (fail before T026–T028): a YouTube publication with an eligible `PublishCheck` shows **Publish now**; clicking it opens `PublishNowDialog` with every `summary` item; **Cancel** calls nothing; **Publish** calls `publishNow` once even on double click (button disabled after the first click); while `publishing` the detail polls every 2 s (fake timers) and shows the progress bar and percentage; edit forms are hidden; on `published` it shows the date, **Open on YouTube** (`target="_blank"`, `rel="noopener noreferrer"`, href = `external_url`), the real privacy and processing status; polling stops.

### Implementation for User Story 1

- [X] T022 [US1] Create `backend/app/youtube_publishing.py` with the YouTube adapter (makes T019–T020 pass together with T025):
  - **`YouTubePublisher(gateway: GoogleGateway, credential_store: CredentialStore, upload_settings: YouTubeUploadSettings)`**: every YouTube-specific dependency is a constructor argument; it only receives the generic `PublishContext` in its protocol methods.
  - **Options**: `get_options(session, publication_id)` returning the stored row or defaults (`private`, `None`, `None`, `False`); router `GET`/`PUT /api/publications/{id}/youtube-options` per [contracts/api.md](contracts/api.md): `404`, `409 platform_not_supported` for non-YouTube accounts, `ensure_editable` (from T014; `cancelled` also → `publication_not_editable`), idempotent upsert with `updated_at`; register the router in `main.py`.
  - **Metadata**: `build_description(description, hashtags)` (research §12: description, blank line, `#a #b`; only hashtags; only description; empty) and `validate_metadata(title, description) -> list[PublishProblem]` (title non-empty after strip, ≤ 100 characters, no `<`/`>`; description ≤ 5000 UTF-8 bytes, no `<`/`>`; fields `title`/`description`).
  - **`check`**: local checks in the contract order (content is video, file exists/readable/size equals `size_bytes`, metadata, options complete, OAuth configured, connection `connected`) returning `PublishProblem`s, plus the `summary` items (Title, Channel `title (channel_id)`, Privacy, Notify subscribers, Made for kids, Altered or synthetic content, File `name (size)`).
  - **`prepare`**: `get_valid_credentials` (with its own `credential_store` and `gateway`) and `list_channels` from `youtube_connections` (expose `_list_channels` as `list_channels`); exactly one channel equal to the linked `channel_id`, otherwise `mark_reconnect_required` + `ConflictError("reconnect_required")`; builds the `video` resource, MIME type (`mp4` → `video/mp4`, `mov` → `video/quicktime`, `webm` → `video/webm`) and the whitelisted `submitted` dict; the opaque `payload` holds no token.
- [X] T023 [US1] Implement the resumable protocol in `backend/app/youtube_upload.py` (happy path + write-ahead, research §3 and §5): `ResumableUpload(client, settings: YouTubeUploadSettings).run(prepared, reporter, token_provider)` — session start (`Location` required, kept only in a local variable), chunked `PUT`s whose body is a generator reading `slice_size` pieces from the file opened in `rb` (explicit `Content-Length`, per-request timeouts connect 10 s / write 60 s / read 60 s), `308` handling, `reporter.report_bytes`, `reporter.enter_final_chunk()` before the request containing the last byte (abort determined if it returns `False`), final resource parsing; a valid video ID matches `^[A-Za-z0-9_-]{11}$`; URL `https://www.youtube.com/watch?v=<id>`. Makes T018 pass.
- [X] T024 [US1] Implement `YouTubePublisher.upload` and `refresh_details` in `backend/app/youtube_publishing.py`: token provider that calls `get_valid_credentials` in a fresh session from `ctx.session_factory` before each request when the token expires within 60 s; maps the final resource to `PublishOutcome` (`details.privacy_status`, `details.upload_status`; warning `privacy_differs` with a fixed message when it differs from the requested privacy); `refresh_details` uses `gateway.get_video_status` and refines `details`/`warnings`. In `backend/app/main.py`, construct `YouTubePublisher(gateway=app.state.google_gateway, credential_store=app.state.credential_store, upload_settings=youtube_upload_settings or YouTubeUploadSettings())` and register it in `app.state.publishers[Platform.YOUTUBE]`.
- [X] T025 [US1] Add the generic endpoints to `backend/app/publishing.py` (router `prefix="/api"`) and the service `start_publication(session, publication_id, *, confirm_remote_checked, ctx, runner, publishers)` per [plan.md](plan.md) Design Notes — a plain function with no FastAPI types, which the endpoint calls after resolving `app.state`: `GET /publications/{id}/publish-check` (local only: generic state/ownership checks + `publisher.check` + `requires_remote_check`; unsupported platform → problem `platform_not_supported`), `POST /publications/{id}/publish` (`202`, preflight order of [contracts/api.md](contracts/api.md), first problem raised with its HTTP code), `GET /publications/{id}/attempts` (newest first). Makes T017 and T019 pass.
- [X] T026 [P] [US1] Create `frontend/src/components/PublishNowDialog.tsx`: loads `getPublishCheck` on open; renders `summary` label/value pairs as-is; if not `eligible`, lists `problems` and disables **Publish**; **Publish** calls `publishNow` and is disabled from the first click until the response; shows API errors with `toApiError(...).message`.
- [X] T027 [P] [US1] Create `frontend/src/components/PublicationAttempts.tsx`: for `latest_attempt` shows the progress bar (`progress`, `bytes_sent` / `total_bytes`), the result (`Open on YouTube`, real privacy, `warnings`, processing status) or the error; below, the attempt history from `listAttempts` (start, end, status, error code/message).
- [X] T028 [US1] Update `frontend/src/components/PublicationDetail.tsx`: **Publish now** button for YouTube publications in `unscheduled`/`scheduled`/`failed` that opens `PublishNowDialog`; after publishing, poll `getPublication` every 2 s while `status === "publishing"` (cleared on unmount); hide schedule/metadata forms and cancel in `publishing`/`published` (and the schedule form in `failed`); render `PublicationAttempts`. Makes T021 pass.

**Checkpoint**: MVP funcional — se puede publicar un vídeo de principio a fin con el
simulador y, manualmente, con YouTube real (quickstart §3); todo el preflight está cubierto.

---

## Phase 4: User Story 2 - Configurar las opciones de YouTube de una publicación (Priority: P1)

**Goal**: privacidad, Made for Kids, synthetic media y Notify subscribers, persistentes y
decididos explícitamente antes de publicar.

**Independent Test**: defaults `private` / sin declarar / sin declarar / `No`; cambiar y
guardar; reiniciar y comprobar persistencia; con declaraciones sin responder, `Publish now`
se rechaza indicando qué falta.

### Tests for User Story 2 ⚠️

- [X] T029 [P] [US2] Write `backend/tests/test_youtube_options.py`: defaults without row (`complete = false`, `editable = true`); `PUT` stores and returns values, is idempotent and does not create rows for other publications; `null` resets a declaration; invalid privacy, missing fields and extra fields → `422`; non-YouTube account → `409 platform_not_supported`; `404`; `editable`/`PUT` per state (`unscheduled`, `scheduled`, `failed` allowed; `publishing`, `published`, `cancelled` → `409 publication_not_editable`); persistence across app restart; `POST .../publish` with a missing declaration → `409 youtube_options_incomplete` with `fields` naming it and no upload request in the fake; mapping of `made_for_kids`, `contains_synthetic_media` and `notify_subscribers` (both `true` and `false`) to the session start request.
- [X] T030 [P] [US2] Write `frontend/src/components/YouTubePublishOptions.test.tsx`: renders privacy radio (`private` default), Made for Kids and Altered/synthetic content as Yes/No with an explicit "Not declared" state, Notify subscribers Yes/No (`No` default); saving calls `saveYouTubeOptions` with the four fields; the unverified-project note is visible; read-only when `editable` is `false`; not rendered for non-YouTube publications (no request made).

### Implementation for User Story 2

- [X] T031 [US2] Complete the options rules in `backend/app/youtube_publishing.py` so T029 passes (completeness → `youtube_options_incomplete` problem with one `fields` entry per missing declaration; `editable` computed with `ensure_editable`).
- [X] T032 [US2] Create `frontend/src/components/YouTubePublishOptions.tsx` and render it in `frontend/src/components/PublicationDetail.tsx` only when `publication.account.platform === "youtube"`; after saving, reload the publish check so **Publish now** reflects the new state. Note text: "YouTube may restrict videos uploaded from unverified API projects to private." Makes T030 pass.

**Checkpoint**: US1 + US2 cubren el flujo principal completo de la spec.

---

## Phase 5: User Story 3 - Validar todo antes de cualquier efecto externo (Priority: P1)

**Goal**: el usuario ve, antes de pulsar, por qué no puede publicar; `publish-check` y
`POST /publish` coinciden siempre. (Las pruebas exhaustivas de cada condición ya existen
desde T019–T020.)

**Independent Test**: para cada condición del preflight, `publish-check` devuelve el mismo
problema que `POST /publish` sin ninguna petición de red, y la interfaz deshabilita
**Publish now** mostrando el motivo.

### Tests for User Story 3 ⚠️

- [X] T033 [P] [US3] Add to `backend/tests/test_publish_preflight.py`: for every local condition of T019, `GET .../publish-check` returns the same problem code (and `field`) that `POST .../publish` raises, without any network request (the fake records nothing); `eligible = true` with a complete `summary` for a valid publication.
- [X] T034 [P] [US3] Add to `frontend/src/components/PublicationDetail.test.tsx`: with problems in the publish check, **Publish now** is disabled and the problem messages are listed next to it (e.g. "YouTube only accepts video content", title too long).

### Implementation for User Story 3

- [X] T035 [US3] Make T033 pass in `backend/app/publishing.py` and `backend/app/youtube_publishing.py`: a single local-check path shared by `publish-check` and `POST /publish` (no duplicated logic), same order and field names as the contract.
- [X] T036 [US3] Show publish-check problems in `frontend/src/components/PublicationDetail.tsx` (disabled button + list), reloading the check when the publication or its options change. Makes T034 pass.

**Checkpoint**: todas las salvaguardas previas a la subida verificadas y visibles.

---

## Phase 6: User Story 4 - Ver y entender los fallos de una ejecución (Priority: P2)

**Goal**: recuperación limitada dentro del mismo intento (backoff + `Retry-After`) y fallos
definitivos clasificados con mensajes comprensibles.

**Independent Test**: con el simulador, los cortes y 5xx recuperables terminan `published`
con un solo intento y un solo vídeo; los errores definitivos dejan `failed` con el código y
mensaje correctos, sin secretos.

### Tests for User Story 4 ⚠️

- [X] T037 [P] [US4] Add to `backend/tests/test_publish_upload.py` the recovery cases: transport error mid-upload (bytes stored by the server) → status query + resume from the confirmed byte, one attempt, one video, bytes identical; `500`/`502`/`503`/`504`/`429`/`403 rateLimitExceeded` recovered; transport error and `5xx` on the session start retried; backoff sequence recorded in `recorded_sleeps` (1, 2, 4… with jitter bounds, capped at 32 s); counter reset after progress; 6 consecutive failures → `failed` `youtube_unavailable` or `network_error`, `outcome_determined = true` when not in `final_chunk`.
- [X] T038 [US4] Add `Retry-After` cases to `backend/tests/test_publish_upload.py`: `503` with `Retry-After: 10` → wait = max(backoff, 10); with an HTTP date → equivalent seconds; `Retry-After: 120` (> 60) → no retry, `failed` `youtube_unavailable`, determined if before `final_chunk`; unreadable/negative values ignored (normal backoff); every wait recorded ≤ 60 s.
- [X] T039 [US4] Add definitive error cases to `backend/tests/test_publish_upload.py`, each asserting `failed`, the error code of [research.md §6](research.md), the fixed message and no retry: `403 quotaExceeded` → `quota_exceeded`; `400 uploadLimitExceeded` → `upload_limit_exceeded`; `403 forbidden` → `permission_denied`; `400 invalidTitle` → `invalid_metadata`; other `400` → `youtube_rejected`; `404` on the session in `uploading` → `upload_session_expired` (determined); `401` → one forced refresh and success; `401` twice → `reconnect_required` and connection marked; refresh `invalid_grant` mid-upload → `reconnect_required`; file deleted mid-upload → `media_unavailable`; the Google error body text never appears in the stored message.
- [X] T040 [P] [US4] Add to `frontend/src/components/PublicationDetail.test.tsx` and `PublicationAttempts` tests: a `failed` publication shows the last error message and the attempt history; **Publish now** is available again (determined failure).

### Implementation for User Story 4

- [X] T041 [US4] Implement recovery in `backend/app/youtube_upload.py` (research §4): classification of transport errors and `500/502/503/504/429/403 rate limit` as recoverable; status query `bytes */TOTAL` after a failure once the session exists; repeat of the session start before it exists; exponential backoff with jitter (1 s up to `max_backoff`) through `YouTubeUploadSettings.sleep`; `Retry-After` parsing (seconds or HTTP date) with `wait = max(backoff, retry_after)`, `> max_retry_wait` → stop with `youtube_unavailable`; at most `max_consecutive_failures` consecutive failures without progress; `401` → `token_provider(force_refresh=True)` once. Makes T037–T038 pass.
- [X] T042 [US4] Implement definitive error classification in `backend/app/youtube_upload.py` / `backend/app/youtube_publishing.py`: reason → code table of research §6, fixed messages, `PublishFailure(code, message, determined)` with `determined = stage != final_chunk`; `ConflictError("reconnect_required")` from `get_valid_credentials` → `PublishFailure("reconnect_required")`; short file read → `media_unavailable`. Makes T039 pass.
- [X] T043 [US4] Show failures in `frontend/src/components/PublicationAttempts.tsx` and allow **Publish now** from `failed` in `frontend/src/components/PublicationDetail.tsx`. Makes T040 pass.

**Checkpoint**: subidas robustas ante cortes y errores claros para todos los fallos.

---

## Phase 7: User Story 5 - Evitar ejecuciones duplicadas y resultados ambiguos (Priority: P2)

**Goal**: nunca dos subidas a la vez, nunca resubir tras un resultado ambiguo o un reinicio.

**Independent Test**: dos `Publish now` simultáneos → una sola sesión; reinicio con un
intento en `uploading` → `failed` determinado; en `final_chunk` → `failed` ambiguo con
revisión manual; volver a publicar exige `confirm_remote_checked`.

### Tests for User Story 5 ⚠️

- [X] T044 [P] [US5] Write `backend/tests/test_publish_concurrency.py`: two threads call `POST .../publish` at once (the fake blocks `channels.list` on a `threading.Event` until both requests have arrived, so both pass the preflight) → exactly one `202` and one `409 publication_in_progress`, one attempt, one session start; a second `POST` while `publishing` → `409`; `POST .../youtube-connection/authorize` and `.../disconnect` for an account with a `publishing` publication → `409 publication_in_progress` and the credentials remain in the store; two different publications of the same account can run at once; **deactivation during `publishing` does not cancel (C6)**: `fake_google.block_uploads(at="chunk")`, `POST .../publish`, `wait_until_blocked()`, then deactivate the account through `PATCH /api/accounts/{id}` (and, in a second run, the project through its endpoint) → both succeed; `release()` and `wait_idle` → the execution was not cancelled: publication `published`, attempt `succeeded` with the video ID returned by the fake; a new `POST .../publish` on another publication of that account is now rejected with `account_inactive` (resp. `project_inactive`).
- [X] T045 [P] [US5] Write `backend/tests/test_publish_ambiguity.py`: transport failure on the last chunk followed by status queries that keep failing → `failed`, `outcome_determined = false`, `requires_manual_review = true`, no second session started; a `308` with a shorter `Range` after the last chunk → back to `uploading`, write-ahead repeated before resending, success; `404` on the session in `final_chunk` → ambiguous; final `200` without a valid video ID → `unexpected_response`, ambiguous; `set_stage` commit failure before the last chunk (patch the helper) → last chunk never sent, `failed` determined; `persist_success` failing on every retry (patch the helper) → `result_not_saved`, ambiguous, `external_id`/`external_url` `NULL`, and `FAKE_VIDEO_ID` absent from the SQLite dump and from `caplog` at DEBUG.
- [X] T046 [US5] Add to `backend/tests/test_publish_ambiguity.py` the manual-review rule: after an ambiguous failure, `POST .../publish` without `confirm_remote_checked` → `409 remote_check_required` (no request to the fake); with it → new attempt; `publish-check` reports `requires_remote_check = true`; the rule also applies after `cancel` + `reactivate` and to a new publication of the same content + account; after a determined failure no confirmation is needed.
- [X] T047 [P] [US5] Write `backend/tests/test_publish_recovery.py`:
  - **Restart recovery**: database with a `publishing` publication and a `running` attempt in `uploading` (via `run_sql`) → new app start → attempt `failed`/`interrupted`/`outcome_determined = true`, publication `failed`, zero requests to the fake; same with `final_chunk` → `outcome_determined = false`, `requires_manual_review = true`; a `published` publication is untouched by the restart; a `scheduled` publication whose date has passed stays `scheduled` after start (no automatic execution).
  - **Deterministic graceful shutdown** (no reliance on closing the `TestClient`, accidental timeouts or daemon threads): `fake_google.block_uploads(at="chunk")`; `POST .../publish`; `fake_google.wait_until_blocked()`; call `app.state.publication_runner.stop()` from a helper thread (it sets `stop_event`); `fake_google.release()` so the blocked request returns; the runner sees `should_stop()` before the next slice and closes the attempt; `stop()` returns and `runner.is_live(attempt_id)` is `False`; assert attempt `failed`/`interrupted`/`outcome_determined = true` (stage `uploading`), publication `failed`, and no further upload request after the release.
- [X] T048 [P] [US5] Add frontend tests in `frontend/src/components/PublicationDetail.test.tsx`: a `failed` publication with `requires_manual_review` shows "Check YouTube Studio" with the channel (`submitted.channel_title` / `channel_id`), title and approximate time (`started_at`–`finished_at`); **Publish** in the dialog stays disabled until the mandatory checkbox "I checked YouTube Studio and this video was not published" is ticked, then `publishNow(id, true)` is called.

### Implementation for User Story 5

- [X] T049 [US5] Make T044 pass: verify the atomic transition of T010 under concurrency; add the `publishing` guard (`409 publication_in_progress`) to `authorize` and `disconnect` in `backend/app/youtube_connections.py`.
- [X] T050 [US5] Implement the ambiguity rules in `backend/app/youtube_upload.py` and `backend/app/publishing.py` (research §5, §7): status queries in `final_chunk` without leaving the stage, `leave_final_chunk()` on an authoritative incomplete `308`, `404` in `final_chunk` → ambiguous, invalid final ID → `unexpected_response` ambiguous, `result_not_saved` path without storing or logging the video ID. Makes T045 pass.
- [X] T051 [US5] Enforce `confirm_remote_checked` in `start_publication` with `requires_remote_check` (pair content + account) and expose it in `publish-check` in `backend/app/publishing.py`. Makes T046 pass.
- [X] T052 [US5] Make T047 pass: `recover_interrupted_attempts` runs in `lifespan` before serving, and `PublicationRunner.stop()` + the reporter's `should_stop()` close `preparing`/`uploading` attempts as `interrupted` determined, in `backend/app/publishing.py`.
- [X] T053 [US5] Implement the manual-review notice in `frontend/src/components/PublicationAttempts.tsx` and the mandatory checkbox in `frontend/src/components/PublishNowDialog.tsx` (shown when `requires_remote_check`). Makes T048 pass.

**Checkpoint**: garantías anti-duplicado completas.

---

## Phase 8: User Story 6 - Publicar antes de hora una publicación programada (Priority: P2)

**Goal**: `Publish now` sobre `scheduled` avisa de que se publica antes de su hora y conserva
la fecha como histórico.

**Independent Test**: publicación `scheduled` para mañana → confirmación con el aviso →
`published` con `scheduled_at` conservado y no elegible para nada más.

- [X] T054 [P] [US6] Add to `backend/tests/test_publish_upload.py`: publishing a `scheduled` publication → `published` with the original `scheduled_at` kept and `published_at` set; `publish-check` returns `scheduled_at`; the session start request has no `publishAt`; a second `POST .../publish` → `409 publication_not_eligible`.
- [X] T055 [P] [US6] Add to `frontend/src/components/PublicationDetail.test.tsx`: the dialog for a `scheduled` publication shows "This publication is scheduled for <local date>. It will be published now, before its scheduled time."; a `published` publication shows its original scheduled date as history.
- [X] T056 [US6] Implement the scheduled notice in `frontend/src/components/PublishNowDialog.tsx` and the historical date in `frontend/src/components/PublicationDetail.tsx`; fix any backend gap found by T054.

---

## Phase 9: User Story 7 - Ver el estado real de las publicaciones en la Queue (Priority: P3)

**Goal**: la Queue muestra `publishing` (progreso), `published` (enlace, aviso de
privacidad) y `failed` (error, revisión manual) y se actualiza sola mientras algo se publica.

**Independent Test**: con publicaciones en los seis estados, la Queue las ordena y muestra
según el estado; el progreso se actualiza sin recargar.

- [X] T057 [P] [US7] Add to `backend/tests/test_publications_queue.py`: order `publishing`, `failed`, `scheduled` (date ↑), `unscheduled` (created ↑), `published` (`published_at` ↓), `cancelled` (`updated_at` ↓), ties by `id`; each item includes `latest_attempt` with a single aggregate query (assert the number of SQL statements with an event listener stays constant as items grow).
- [X] T058 [P] [US7] Add to `frontend/src/components/PublicationQueue.test.tsx`: sections for the new states in backend order; a `publishing` row shows its progress and the list is polled every 2 s only while some row is `publishing`; a `published` row shows **Open on YouTube** and the privacy warning when present; a `failed` row shows the last error summary and "Manual review required" when applicable.
- [X] T059 [US7] Update `frontend/src/components/PublicationQueue.tsx` (sections, row content, polling cleared on unmount) and make T057 pass in `backend/app/publications.py` if needed. Makes T058 pass.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T060 [P] Write the end-to-end leak tests:
  - **Backend, `backend/tests/test_publish_secrets.py`**: after a successful upload, a recovered upload, a failed upload and a `result_not_saved` case, with `caplog` at DEBUG on the root logger, assert that `FAKE_UPLOAD_ID`, `FAKE_ACCESS_TOKEN`, `FAKE_REFRESHED_ACCESS_TOKEN`, `FAKE_REFRESH_TOKEN` and `"Bearer "` never appear in the SQLite `.dump`, in any JSON response of the publishing, attempts, publications and queue endpoints, or in the logs; `FAKE_VIDEO_ID` never appears in the logs.
  - **Frontend, `frontend/src/storage-safety.test.tsx`** (C2): (1) a static check over every non-test source file under `frontend/src/` asserting that the application code does not reference `localStorage`, `sessionStorage`, `indexedDB` or `document.cookie` — today AutoPublisher uses none of them, and the test documents and enforces that; (2) a runtime check that renders `PublicationDetail` through the full publish flow with `FakeApi` (options, publish check, `publishNow`, progress, success with `external_url`, failure with manual review) while spying on `Storage.prototype.setItem`, `indexedDB.open` and the `document.cookie` setter, and asserts none was called, so no token, session URL, `Authorization` header or execution data is persisted in the browser.
- [X] T061 [P] Update `README.md` with a "Publishing to YouTube" section: flow (Publish now → confirmation → progress → Published), YouTube options and their defaults (`private`; Made for Kids and altered/synthetic content must be declared; Notify subscribers defaults to No), unverified API projects restricted to private and the YouTube audit, current `videos.insert` quota with the consultation date (2026-10-07) and a link to the official page (not hard-coded), what "manual review required" means and how to check YouTube Studio by channel, title and time, delete test videos in YouTube Studio, no scheduler yet; add the new API routes to the API section.
- [X] T062 Run every quality gate: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`. Fix every failure; report any check that cannot pass.
- [X] T063 Run the manual validation of [quickstart.md](quickstart.md) §3–§6 against real YouTube with a small test video in `private`, using the implementation as designed: `videos.insert` **without** `categoryId` (research §12). The manual validation must not introduce new functional decisions.
  - **If YouTube accepts the upload**: record in the PR that "upload without `categoryId`" is **validated**, together with the time to `Publishing` and the observed progress cadence, without video IDs or URLs. Continue with the rest of the quickstart and delete the test videos in YouTube Studio.
  - **If YouTube rejects the upload specifically because `categoryId` is required**: **stop** the validation; report the error (HTTP status, error code/reason and the AutoPublisher error shown, without tokens, session URIs, video IDs or raw Google bodies); **do not** modify code; **do not** add `categoryId=22` or any other category; leave T063 **unchecked** until the design is explicitly reviewed and the spec/plan are updated.
  - **Validated 2026-10-07** (real channel, private, 11.5 MB synthetic test video, two uploads): upload without `categoryId` **validated** (YouTube assigned its own category); `202` in ~0.6 s; progress visible every ~1–2 s over 2 resumable chunks; one `succeeded` attempt per publication; real privacy `private` = requested; result persisted after restarting backend and frontend, with no new upload; local file byte-identical. The first run found the session id leaking in DEBUG logs through the `X-GUploader-UploadID` response header; the log filter now redacts it (unit test + second real upload confirm). No tokens, `Authorization`, session URLs or video IDs in logs; video IDs only in SQLite and API responses. The first test video was deleted manually in YouTube Studio and the second one is pending manual deletion; local test data removed afterwards.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; **bloquea** todas las historias.
- **US1 (Phase 3)**: depende de Foundational. Es el MVP e incluye las pruebas exhaustivas del
  preflight.
- **US2 (Phase 4)**: depende de US1 (los endpoints de opciones y el publisher se crean en
  T022; US2 completa reglas y UI).
- **US3 (Phase 5)**: depende de US1 (paridad `publish-check` ↔ `POST /publish` e interfaz).
- **US4 (Phase 6)**: depende de US1 (amplía `youtube_upload.py`).
- **US5 (Phase 7)**: depende de US1; T050 depende de T041 (US4) porque las consultas de
  estado en `final_chunk` reutilizan la recuperación.
- **US6 (Phase 8)**: depende de US1.
- **US7 (Phase 9)**: depende de Foundational (orden y `latest_attempt`) y de US1 para el
  contenido de las filas.
- **Polish (Phase 10)**: depende de todas las historias deseadas.

### Tests before implementation

- **Foundational**: T002–T004 no necesitan ninguna abstracción nueva (solo `httpx2`, los
  fakes existentes y `run_sql`) y se escriben primero. T008 y T015 escriben su test antes de
  su implementación dentro de la propia tarea. **T013** (helpers y fixtures de
  `conftest.py`) se escribe **después** de T009–T012 porque usa `PublishingSettings`,
  `YouTubeUploadSettings` y `PublicationRunner`; ningún test anterior a T013 depende de
  ellos.
- **US1**: T017–T021 (incluidas las pruebas exhaustivas del preflight T019–T020) preceden a
  T022–T028; ninguna comprobación del preflight se implementa sin un test previo.
- **Resto de historias**: los tests de cada fase preceden a su implementación.
- Backend antes que frontend cuando el frontend consume un endpoint nuevo.
- `youtube_upload.py` (protocolo) antes que `YouTubePublisher.upload`.

### Parallel Opportunities

- Foundational: T002, T003, T004 (tests) en paralelo; T008, T015 y T016 en paralelo con
  T009–T012.
- US1: T017–T021 en paralelo; T026 y T027 en paralelo con el backend.
- US2–US4, US6 y US7 pueden avanzar en paralelo tras US1 si hay varias personas; US5
  necesita T041.
- Dentro de cada historia, los tests marcados [P] se escriben en paralelo.

---

## Parallel Example: User Story 1

```bash
# Tests de US1 a la vez:
Task: "T017 Write test_publish_upload.py (happy path) and test_publish_service.py"
Task: "T018 Write backend/tests/test_youtube_upload.py (protocol unit tests)"
Task: "T019 Write backend/tests/test_publish_preflight.py (exhaustive preflight)"
Task: "T020 Write backend/tests/test_youtube_metadata.py"
Task: "T021 Write PublicationDetail.test.tsx publishing cases"

# Componentes de frontend mientras se implementa el backend:
Task: "T026 Create frontend/src/components/PublishNowDialog.tsx"
Task: "T027 Create frontend/src/components/PublicationAttempts.tsx"
```

## Parallel Example: User Story 5

```bash
Task: "T044 Write backend/tests/test_publish_concurrency.py"
Task: "T045 Write backend/tests/test_publish_ambiguity.py"
Task: "T047 Write backend/tests/test_publish_recovery.py"
Task: "T048 Manual-review frontend tests"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 + Phase 2.
2. Phase 3 (US1): publicar de principio a fin con el simulador, con el preflight completo
   cubierto por tests.
3. **Parar y validar**: tests de US1 en verde; opcionalmente quickstart §3 con YouTube real.

### Incremental Delivery

1. US1 → MVP.
2. US2 + US3 → flujo principal completo y seguro (todas las P1).
3. US4 + US5 → robustez y garantías anti-duplicado (P2).
4. US6 → publicación anticipada de programadas.
5. US7 → Queue completa.
6. Polish → secretos, README, quality gates, validación real.

### Notes

- Commits pequeños en inglés, por tarea o grupo lógico, solo cuando el usuario lo pida.
- No ampliar el alcance: nada de scheduler, retries entre intentos, `publishAt`, tags,
  thumbnails, playlists, borrado ni otras plataformas.
