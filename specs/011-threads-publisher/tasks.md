---

description: "Task list for real Threads text, image and video publishing (Feature 011)"
---

# Tasks: Publicación real de texto, imagen y vídeo en Threads

**Input**: Design documents from `specs/011-threads-publisher/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-055, SC-011). Ningún test usa Internet, Meta
real, R2 real ni el keyring real: `FakeThreads` (ampliado), `FakeMediaDeliveryProvider`,
`InMemoryCredentialStore`, `FakeClock`, `probe_video_streams` simulado y `sleep` instantáneo.
En cada historia los tests se escriben primero y deben fallar antes de implementar. Durante
la implementación se ejecutan tests dirigidos (`uv run pytest tests/test_threads_….py`); la
suite completa solo en los checkpoints marcados y en la fase final.

**Organization**: tareas agrupadas por historia de usuario (US1–US8 de la spec). Código,
comentarios, mensajes de API/UI, README, docs y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes).
- **[Story]**: historia de usuario (US1–US8).

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`.
- Frontend: `frontend/src/`, `frontend/src/components/`.
- Comandos de backend desde `backend/` (`uv run …`); de frontend, desde `frontend/` (`npm …`).

## Reglas transversales (aplican a todas las tareas)

- **Protocolo Meta** (research §1; no inventar nada más): host y versión de las constantes
  existentes `THREADS_GRAPH_HOST` / `THREADS_API_VERSION` de `threads_gateway.py` (no
  duplicarlas). `{user}` = `ThreadsConnection.threads_user_id` (nunca `/me`).
  - Container: `POST /v1.0/{user}/threads`, cuerpo `application/x-www-form-urlencoded`
    (`httpx` `data=`), **sin query string**: `media_type` (`TEXT`|`IMAGE`|`VIDEO`),
    `text` (omitido si vacío), `image_url` | `video_url`, `alt_text` (solo si no vacío),
    `access_token`. Nunca `auto_publish_text` ni otros parámetros opcionales.
  - Estado: `GET /v1.0/{container_id}?fields=id,status,error_message`.
  - Publicar: `POST /v1.0/{user}/threads_publish`, cuerpo de formulario `creation_id`,
    `access_token` → `{"id": "<THREADS_MEDIA_ID>"}`.
  - Post publicado: `GET /v1.0/{post_id}?fields=id,permalink,timestamp`.
  - Cuota: `GET /v1.0/{user}/threads_publishing_limit?fields=quota_usage,config`.
  - **Prohibido** listar posts (`GET /{user}/threads`) para identificar un post.
- **Espera por tipo** (research §10, revisado tras la validación real temprana): tras crear
  el container, lectura de estado inmediata; publicable solo si `FINISHED` **y** antigüedad
  ≥ `MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS` (30 s, política del producto, regla común a
  texto, imagen y vídeo) medida desde `container_created_at` persistido con el reloj
  inyectable; un container `FINISHED` más joven espera solo lo que le falta (nunca un
  `sleep(30)` fijo) y se relee antes del write-ahead. Si `IN_PROGRESS`/desconocido/lectura temporal fallida:
  esperas `TEXT` 2, 5, 10, 15 s y luego cada 15 s (≤ 1 min); `IMAGE` 2, 5, 10, 15 s y
  luego cada 30 s (≤ 3 min); `VIDEO` 10, 20, 30 s y luego cada 60 s (≤ 5 min). Esperas
  troceadas en 1 s con `should_stop`; el timeout de cada tipo se cuenta desde la creación del
  container.
- **Anti-duplicados** (research §11–§12): un container por intento, sin reutilización;
  `container_id` persistido (commit) inmediatamente tras crearlo; write-ahead
  (`threads_publish_runs.phase = 'publishing'` + `publish_started_at`, commit; después
  `reporter.enter_finalizing()` debe devolver `True`) **antes** de `threads_publish`;
  `threads_publish` **como máximo una vez** por container y nunca reintentado. Rechazo
  explícito → una lectura del container (`PUBLISHED` → éxito sin identidad remota; si no,
  fallo determinado). No concluyente → lecturas del container original a 0, 5, 15, 30, 60 s:
  solo `PUBLISHED` resuelve (sin identidad remota, aviso `remote_identity_unavailable`);
  cualquier otro estado o lectura fallida → `threads_publish_uncertain` (`determined=False`).
- **Permalink no bloqueante** (research §13): con post ID el resultado está determinado;
  fallo/ausencia/omisión de permalink → `external_id` = post ID, `external_url = None`, aviso
  `permalink_unavailable`, `PUBLISHED`/`succeeded`. Nunca un enlace construido.
- **Cuota** (research §9): forma entendida → agotada falla `409
  threads_publishing_limit_reached`; `ThreadsUnavailable` → continúa con aviso
  `quota_unavailable`; forma inesperada o `ThreadsRejected` → `502
  threads_unexpected_response`; credencial/permiso → `threads_reconnect_required`.
- **Preflight** (FR-025/FR-026): solo lecturas locales, inspección de media, credencial y
  lecturas a Meta (`verify_identity`, cuota, container anterior). Antes de superarlo **nunca**
  se sube nada al proveedor ni se crea un container. El texto nunca usa media delivery.
- **Orden éxito → limpieza** (FR-045): `persist_success` del ejecutor genérico y **después**
  `publisher.release(...)`; un fallo de limpieza solo añade `temporary_media_cleanup_failed`.
- **Secretos**: token de Threads, URLs prefirmadas, `X-Amz-*`, credenciales del proveedor y
  respuestas crudas de Meta nunca en SQLite, logs, errores, JSON ni navegador. Excepciones del
  gateway sin cuerpo/URL/token y `from None`.
- **Neutralidad**: `publishing.py`, `publications.py`, `scheduler.py`, `automation.py` y
  `accounts.py` no contienen `threads_` ni importan `app.threads*`; `threads_*` no importa
  `app.instagram*`. Errores con `AppError`/`ConflictError`/`PublishFailure` y los códigos
  exactos de [contracts/api.md](contracts/api.md) (≤ 40 caracteres).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: fixtures y fakes base de Threads publishing.

- [X] T001 Extend `FakeThreads` in backend/tests/fakes.py: `POST /v1.0/{user}/threads` (records form body, rejects any parameter in the query string, returns sequential container ids, scripted failures incl. `THREADS_API__LINK_LIMIT_EXCEEDED`), container status `GET` with a scripted status/`error_message` sequence per container (default `FINISHED`), `POST …/threads_publish` (success; explicit 4xx; timeout/transport/5xx/429 that **did** or **did not** publish, marking the container `PUBLISHED` accordingly), post `GET` (`permalink`, `timestamp`, permalink omitted, temporary failure, unexpected shape), `threads_publishing_limit` (valid shape with/without `data`, exhausted, 5xx, unexpected shape, 4xx); counters of containers created and publishes per container; a request to the post **list** endpoint fails the test
- [X] T002 [P] Add `accepts_text_only: bool = False` (programmable) to `FakePublisher` in backend/tests/fakes.py
- [X] T003 Add fixtures to backend/tests/conftest.py: `threads_publishing_client` (app with `FakeThreads`, `InMemoryCredentialStore` holding a connected Threads account, `fake_media_delivery`, `media_delivery_file`, fake clock, instant sleep and short `ThreadsPublishSettings`), helpers `threads_text_publication(...)`, `threads_image_publication(format=…)`, `threads_video_publication(streams=…)`, and a `probe_streams` factory for `VideoStreams`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: migración, cambios neutrales del núcleo (publicaciones sin `Content`), modelos,
gateway, reglas de media sin red, opciones de Threads (backend) y registro del publisher.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta completar esta fase.

### Tests foundational (escribir primero)

- [X] T004 [P] Extend backend/tests/test_migrations.py for `0010`: upgrade from `0009` with existing publications keeps every row and CHECK; `publications.content_id` accepts NULL; `uq_publications_active_content_account` still has its `WHERE` clause and still rejects two active publications of the same content and account; tables `threads_publication_options` and `threads_publish_runs` with the CHECKs/index of data-model.md; downgrade succeeds with no content-less publication and aborts with a clear error, schema untouched, when one exists
- [X] T005 [P] Extend the existing architecture tests instead of adding duplicates: in backend/tests/test_accounts.py reuse `test_accounts_core_does_not_depend_on_platforms` (extend it only if it does not already reject `app.threads*` imports and `threads_` code in `accounts.py`); in backend/tests/test_publications_states.py add `threads_publishing` and `threads_media` to `test_threads_and_instagram_do_not_depend_on_each_other` and assert `publications.py` does not import `app.publishing`
- [X] T006 [P] Write backend/tests/test_text_publications.py: `POST /api/projects/{id}/text-publications` with a `FakePublisher(accepts_text_only=True)` registered for Threads → 201, `content_id`/`content` null, description/hashtags stored as overrides, `title_override` null, several active text publications for the same account allowed; `422 text_publication_not_supported` (per-account `fields`) for YouTube/Instagram/unregistered platforms; `project_inactive`, `account_inactive`, account of another project, past date, `auto_publish_enabled` without date; queue lists content-less publications in queue order; `PATCH` (text, hashtags, date, arm) and `cancel`/`reactivate` work without file or duplicate checks; `publish-check` gives `publication_media_required` when a content-less publication belongs to a publisher with `accepts_text_only=False` (inserted via SQL) and never calls that publisher's `check`; `requires_remote_check` uses the publication's own attempts when `content_id` is NULL
- [X] T007 [P] Write backend/tests/test_threads_gateway_publish.py against `FakeThreads`: request shapes of research §1 (form bodies, nothing in the query of POSTs, user id path, host/version constants); `create_container` omits empty `text`/`alt_text`; parsing of container id, `(status, error_message)` (unknown `error_message` values dropped), post id, `(permalink, timestamp)` (permalink only if `https://`), quota `(usage, total, duration)` with and without `data`; unexpected quota shape → `ThreadsUnexpectedResponse`; link-limit rejection flagged safely; error classification reuses `_error_for`; no exception text contains bodies, URLs, tokens or `image_url`/`video_url` values
- [X] T008 [P] Write backend/tests/test_threads_media.py (no network): `threads_media_kind`; text = `description_with_hashtags` (no title, no other transformation, exact bytes); conservative length (ASCII, accents count 1; emoji ≥ U+10000 count 4; ZWJ sequences, VS16, keycaps, `So` symbols per research §4); unique links `http://`, `https://`, `www.` (> 5 → problem); `TEXT` empty → problem; `threads_text_invalid` messages include value and limit; never truncated. Images per research §7: JPEG/PNG passthrough byte-identical; static WebP → PNG derivative (same size, EXIF orientation applied, alpha kept, ICC kept), derivative validated (format PNG, ≤ 8 MiB, aspect ≤ 10:1); animated WebP, unreadable file, aspect > 10:1, > 8 MiB (original or derivative) → `threads_image_incompatible`; width outside 320–1440 accepted; original file unchanged. Video per research §8 with fake `VideoStreams`: each mandatory rule (format, size, video stream, codec, width, aspect, duration, FPS, pix_fmt, `moov`, audio codec/sample rate/channels) failing and each missing mandatory value → `threads_video_incompatible` ("could not determine …"); video bitrate from stream, else container, else delegated; audio bitrate ≤ 128 000 when reported, else delegated; `field_order` progressive passes, interlaced fails, missing/`unknown` delegated; `closed_gop`/`edit_lists` always in `delegated_checks`; probe `None` → `threads_media_unverifiable`
- [X] T009 [P] Write backend/tests/test_threads_options.py: `GET/PUT /api/publications/{id}/threads-options` per contracts/api.md (`media_kind`, exact `text`, `text_length`, `text_links`, `alt_text` only image/video trimmed/empty→null, `threads_alt_text_invalid` > 1000, `threads_option_not_applicable` on text, `platform_not_supported`, not editable in `publishing`/`published`/`cancelled`, `media_delivery_required`/`media_delivery_configured`, `problems` without connection codes, `limits`); options persist across app restart; responses contain no provider config or URLs; other platforms never expose Threads options

### Implementation foundational

- [X] T010 Add to backend/app/models.py: `Publication.content_id: Mapped[int | None]`; `ThreadsPublicationOptions`, `ThreadsMediaKind`, `ThreadsPublishPhase`, `ThreadsPublishRun` exactly as data-model.md §2–§3 (named CHECKs, index `(publication_id, container_created_at)`, no relationship from `Publication`)
- [X] T011 Create backend/migrations/versions/0010_threads_publishing.py: batch-recreate `publications` with nullable `content_id` keeping every CHECK, then drop/recreate `uq_publications_active_content_account` with `sqlite_where` (pattern of `0008`); create `threads_publication_options` and `threads_publish_runs`; downgrade first counts `publications` with `content_id IS NULL` and raises `RuntimeError` before touching the schema if any, otherwise drops the two tables and restores `NOT NULL` (same index care)
- [X] T012 Update backend/app/schemas.py: `PublicationRead.content_id: int | None`, `content: PublicationContentSummary | None`; `TextPublicationCreate` (`account_ids` 1–50, `description` with the `DescriptionOverride` rules, `hashtags` normalized like `hashtags_override`, `scheduled_at`, `auto_publish_enabled`, `extra="forbid"`); `ThreadsPublicationOptionsRead`/`Write` and `ThreadsTextLimitsRead` per contracts/api.md
- [X] T013 Make backend/app/publications.py content-optional (neutral, no platform names): `effective_metadata(publication, content: Content | None)`; `publication_to_read`/`publication_read`/`_related` with optional content; `list_publications` uses `outerjoin(Content)`; `ensure_can_prepare` and `_set_consent` check the file only when there is content; `reactivate_publication` skips `find_active` without content; new `POST /projects/{project_id}/text-publications` (all or nothing, severity order of the existing creation, platform support read from `request.app.state.publishers[platform].accepts_text_only` via `getattr(..., False)` without importing `app.publishing`, `422 text_publication_not_supported`)
- [X] T014 Update the generic core in backend/app/publishing.py: `Publisher.accepts_text_only: bool` in the protocol; `PreparedPublication.file_path: Path | None`; `local_check` adds `PublishProblem("publication_media_required", …)` and returns before `publisher.check` when `content_id is None` and the publisher does not accept text-only; `requires_remote_check(session, publication)` (content+account as today, or the publication's own latest attempt without content) used by `start_publication` and `get_publish_check`; no Threads code
- [X] T015 [P] Set `accepts_text_only = False` on `YouTubePublisher` in backend/app/youtube_publishing.py and `InstagramPublisher` in backend/app/instagram_publishing.py
- [X] T016 [P] Neutral changes in backend/app/media_delivery.py: `EXTENSIONS["image/png"] = "png"`; `NOT_CONFIGURED_MESSAGE` without the word Instagram ("…lets the platform fetch the media…", same docs pointer)
- [X] T017 [P] Extend backend/app/threads_gateway.py (research §1, §9–§13): `PUBLISH_TIMEOUT_SECONDS = 60`; `create_container(user_id, token, *, media_type, text, image_url=None, video_url=None, alt_text=None) -> str`; `container_status(container_id, token) -> ContainerState(status, error_message)` (documented `error_message` values only); `publish(user_id, container_id, token) -> str`; `published_media(media_id, token) -> PublishedMedia(permalink, timestamp)`; `publishing_limit(user_id, token) -> PublishingLimit(usage, total, duration)` raising `ThreadsUnexpectedResponse` on any shape not understood; `ThreadsRejected.link_limit_exceeded` flag from `THREADS_API__LINK_LIMIT_EXCEEDED` (no Meta text kept); POST parameters only in `data=`
- [X] T018 [P] Create backend/app/threads_media.py (pure, no network, no Instagram imports): limits constants (500 chars, 5 links, 1000 alt text, 8 MiB, 10:1, video limits of research §8), `threads_media_kind`, `build_text`, `text_length`, `text_links`, `text_problems`, `PreparedImage` + `prepare_threads_image(path, media_format)` + `image_problems`, `VideoCheck(problems, delegated_checks)` + `video_problems(media_format, size, streams, moov_first)`, `CONTENT_TYPES`
- [X] T019 Create backend/app/threads_publishing.py with the options router: `get_options` (defaults without row), `options_to_read`, `GET/PUT /api/publications/{publication_id}/threads-options` (uses `ensure_editable`, `threads_media`, `delivery.configured()`; no network), and a `ThreadsPublisher` skeleton (`accepts_text_only = True`, `ThreadsPublishSettings` per research §10/§12/§13, constructor `(gateway, credential_store, delivery, settings=None)`) that implements **every** method of the generic `Publisher` protocol with its exact signature from the start: `check`, `prepare`, `upload`, `refresh_details`, `release` and `reconcile` (the protocol has no `publish` method: the final publication runs inside `upload`). `check`/`prepare`/`upload`/`refresh_details`/`release` may be minimal until US1 fills them; `reconcile(session, publication, attempt, ctx) -> Reconciliation | None` is a side-effect-free placeholder that returns `None` (no network, no session writes, no reconciliation logic) until T049 replaces it. Goals: `mypy` passes, T020 can register the publisher, and `publish-check`/`Publish now` can call the whole protocol without depending on US7
- [X] T020 Wire in backend/app/main.py: `create_app(..., threads_publish_settings=None)`; register `Platform.THREADS: ThreadsPublisher(gateway=app.state.threads_gateway, credential_store=app.state.threads_credential_store, delivery=temporary_media, settings=...)` and `threads_publishing.router`; remove the "no Threads publisher" comment

**Checkpoint**: migración, núcleo neutral, gateway, reglas de media, opciones y registro
listos; ejecutar la suite completa (`uv run pytest`) — YouTube, Instagram, conexión Threads y
scheduler en verde.

---

## Phase 3: User Story 1 - Publicar ahora un post de texto en Threads (Priority: P1) 🎯 MVP

**Goal**: `Publish now` publica un post de texto (container `TEXT` → write-ahead →
`threads_publish` → permalink) sin media delivery, con el texto exacto.

**Independent Test**: con `FakeThreads`, publicación de texto de una cuenta `Connected` →
`published`, intento `succeeded` (`manual`), post ID y permalink, un container `TEXT`, un
`threads_publish`, cero objetos de media delivery, texto enviado idéntico al mostrado y sin
secretos.

### Tests for User Story 1

- [X] T021 [P] [US1] Write backend/tests/test_threads_publish_text.py: end-to-end text publish; stages `preparing → processing → finalizing → done`; run phases `preparing → creating_container → processing_container → publishing → verifying_result → succeeded`; exactly one container with `media_type=TEXT` and the exact final text (accents, emoji, URL, hashtags block) and no `auto_publish_text`; immediate status read `FINISHED` → waits only up to the 30 s minimum age and reads the status again (corrected after the early real validation); scripted `IN_PROGRESS` → bounded waits then publish; `threads_publish` once; `external_id`/`external_url` = post id/permalink, `details.threads_timestamp`; permalink failing temporarily, missing or omitted → `published`/`succeeded`, `external_url` null, warning `permalink_unavailable`, still one `threads_publish`; no `temporary_media_objects` rows and no provider calls; `submitted` snapshot (data-model.md §4); progress 0.0 until success. **Minimal anti-duplicate guarantees of the MVP** (driving T025): container status read before the final publication (`threads_publish` never called before `FINISHED`); write-ahead committed before the publish request (run phase `publishing` + attempt stage `finalizing` visible inside the fake's publish hook); write-ahead commit failure → `internal_error` determined and **zero** publish requests; explicit rejection (4xx) + container not `PUBLISHED` → `threads_publish_failed` determined; explicit rejection + container `PUBLISHED` → `published` without remote identity; inconclusive result (timeout, transport cut, 5xx, unexpected body) + container `PUBLISHED` → `published`/`succeeded` with `external_id`/`external_url` null and `remote_identity_unavailable`; inconclusive + any other status or failing reads → `threads_publish_uncertain`, `outcome_determined=False`; in every case at most one `threads_publish`, exactly one container in the attempt and no request to the post list endpoint
- [X] T022 [P] [US1] Write frontend/src/components/TextPublicationCreate.test.tsx: form only offers active accounts of `TEXT_POST_PLATFORMS`; sends `description`, parsed hashtags, accounts, optional date and explicit auto-publish consent; shows API field errors (`text_publication_not_supported`); and extend frontend/src/components/PublicationQueue.test.tsx: **New text post** only when the project has an active Threads account; content-less rows show "Text post" and the start of the text; `Open on Threads` only with `external_url`

### Implementation for User Story 1

- [X] T023 [US1] Implement `ThreadsPublisher.check` in backend/app/threads_publishing.py (no network): kind (`threads_media_unsupported`), for image/video the content type matches and the file is present with its size (`media_unavailable`), `text_problems`, `alt_text` validity, `media_delivery_not_configured` (503, image/video only), connection (`threads_not_connected`/`threads_reconnect_required`), summary rows of contracts/api.md
- [X] T024 [US1] Implement `ThreadsPublisher.prepare` base path in backend/app/threads_publishing.py: connection → `verify_identity` + `get_valid_credentials` from threads_connections (Feature 010 errors as is) → `ThreadsPayload` (account id, threads user id, username, kind, text, alt text, content type/source/size or none) → quota (research §9 three cases; `quota_unavailable` warning carried in the payload) → previous-container read (research §11: `PUBLISHED` → `409 threads_already_published`, temporary → `503 threads_unavailable`) → `PreparedPublication(file_path=None, total_bytes=0, submitted=…)` for text
- [X] T025 [US1] Implement `ThreadsPublisher.upload` for text in backend/app/threads_publishing.py, including the **complete** `_publish` and `_uncertain` behaviour of research §12 (the MVP is already duplicate-safe; T021's anti-duplicate cases must pass): create run (`preparing`, commit) → `token` (credential problems → determined failures) → `reporter.enter_processing()` + `creating_container` → `create_container` (one container per attempt, never a second one) → store `container_id`/`container_created_at` (commit) → `processing_container` with `_wait_until_ready` (status read before the final publication; research §10 per-kind waits; publish only when `FINISHED` **and** the container is ≥ `MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS` old; `ERROR` mapping, `EXPIRED`, timeout, shutdown → determined) → write-ahead (`publishing` + `publish_started_at`, then `enter_finalizing()`; if either commit fails → `internal_error` determined and `threads_publish` is **not** called) → `_publish`: `threads_publish` called at most once and never repeated; post ID → success; explicit rejection → one read of the original container (`PUBLISHED` → confirmed without remote identity, otherwise determined `threads_publish_failed`, reconnect marking for credential/permission errors); inconclusive (timeout, cut, 5xx/429/transient codes, unexpected response) → only reads of the original container with `uncertain_waits` (0, 5, 15, 30, 60 s): `PUBLISHED` → confirmed publication with `external_id`/`external_url` = `None` and `remote_identity_unavailable` (never inventing post ID or permalink), anything else → `threads_publish_uncertain` (`determined=False`, message with `@username`, UTC write-ahead time and text start); never listing recent posts → `verifying_result` → `_outcome` (permalink with bounded retries, never raising) → `succeeded`; any exception marks the run `failed`
- [X] T026 [US1] Implement `ThreadsPublisher.refresh_details` (retry permalink once; fill `details.permalink` and remove `permalink_unavailable` only with an official `https://` permalink) and `release` (`release_attempt` + `sweep`; no warning when there are no objects) in backend/app/threads_publishing.py
- [X] T027 [P] [US1] Update frontend/src/types.ts (`content_id: number | null`, `content: PublicationContentSummary | null`, `TEXT_POST_PLATFORMS = ["threads"]` with a comment saying it mirrors the backend publisher capability `accepts_text_only` and must be kept aligned with it, Threads options types) and frontend/src/api.ts (`createTextPublications(projectId, body)`)
- [X] T028 [US1] Create frontend/src/components/TextPublicationCreate.tsx (text area for the description, hashtags input, account checkboxes of `TEXT_POST_PLATFORMS`, date and the existing `AutoPublishConsent`) and add the **New text post** action and content-less rows to frontend/src/components/PublicationQueue.tsx
- [X] T029 [US1] Make frontend/src/components/PublicationDetail.tsx content-optional (title from the text when no content, no `MediaPreview`, `preparationBlocker` without file check) and add `"threads"` to `PUBLISHING_PLATFORMS`; extend frontend/src/test-fake-api.ts with `text-publications`, content-less publications and Threads attempts

**Corrección tras la validación real temprana (2026-10-13)**: `threads_publish` rechazó un
container `TEXT` `FINISHED` publicado ~300 ms tras crearse. T021/T025 se corrigieron con la
antigüedad mínima de research §10 (`MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS = 30` en
backend/app/threads_publishing.py) y backend/tests/test_threads_container_age.py (reloj falso:
`FINISHED` a 0 s / 20 s / 35 s, polling, `ERROR`/`EXPIRED` durante la espera, cierre y
reinicio antes de la antigüedad mínima → determinado, `threads_publish` ≤ 1). US2/US3
reutilizan la misma regla.

**Checkpoint**: un post de texto se publica de extremo a extremo con fakes y desde la
interfaz.

---

## Phase 4: User Story 2 - Publicar ahora una imagen en Threads (Priority: P1)

**Goal**: una imagen (JPEG/PNG tal cual; WebP estático como PNG derivado) se publica usando el
media delivery genérico, con `alt_text`, y se limpia después.

**Independent Test**: con fakes, imagen JPEG con `alt_text` → fila de media temporal antes de
subir, container `IMAGE` con la URL firmada solo en el cuerpo y el `alt_text`, un
`threads_publish`, `published`, objeto borrado tras el éxito, original idéntico.

### Tests for User Story 2

- [X] T030 [P] [US2] Write backend/tests/test_threads_publish_image.py: JPEG, PNG and static WebP (sent as PNG, `converted`, `delivered_format`) end-to-end; stages with `uploading` and real byte progress; `temporary_media_objects` row committed before `put` (provider hook); container `media_type=IMAGE` with `image_url` only in the form body and `alt_text` when set (omitted when empty); immediate `FINISHED` → waits only up to the 30 s minimum container age (common rule, research §10); `IN_PROGRESS` → waits ≤ 3 min; `FAILED_DOWNLOADING_VIDEO`-style fetch error → `threads_media_fetch_failed`; `media_delivery_failed` before any container; original sha256 unchanged
- [X] T031 [P] [US2] Write backend/tests/test_threads_cleanup.py: `release` runs only after `persist_success` (publication already `published` inside the provider delete hook); delete failure → `published`/`succeeded` unchanged, warning `temporary_media_cleanup_failed`, row pending and removed by a later `sweep`; cleanup after determined failures; text attempts never touch the provider

### Implementation for User Story 2

- [X] T032 [US2] Extend `prepare` for images in backend/app/threads_publishing.py: `prepare_threads_image` (derivative bytes or original path, content type, size, `converted`), `threads_image_incompatible` before any delivery; `PreparedPublication(file_path=path, total_bytes=delivered size)`
- [X] T033 [US2] Extend `upload` for images in backend/app/threads_publishing.py: `delivering_media` + `reserve`/`upload` with `reporter.report_bytes` + `public_url` (`MediaDeliveryNotConfigured`/`MediaDeliveryFailed` → determined failures) → container with `image_url=url.reveal()` and `alt_text` → image waits (≤ 3 min)

**Checkpoint**: texto e imagen se publican con fakes.

---

## Phase 5: User Story 3 - Publicar ahora un vídeo en Threads (Priority: P1)

**Goal**: un vídeo compatible se publica tras esperar a `FINISHED` (≤ 5 min); `ERROR`,
`EXPIRED` y timeout fallan sin `threads_publish`; nunca se transcodifica.

**Independent Test**: con fakes, container `IN_PROGRESS` varias lecturas → `FINISHED` →
publicado; `ERROR`/`EXPIRED`/timeout → `failed` determinado, cero `threads_publish`, objeto
borrado.

### Tests for User Story 3

- [X] T034 [P] [US3] Write backend/tests/test_threads_publish_video.py: `media_type=VIDEO`, `video_url` only in the body, `alt_text`; streaming upload progress; waits 10, 20, 30, then 60 s up to 5 min (fake sleep total bounded, no busy loop); `ERROR` + `INVALID_*`/`FAILED_PROCESSING_*` → `threads_media_rejected`, `FAILED_DOWNLOADING_VIDEO` → `threads_media_fetch_failed`, `UNKNOWN` → `threads_processing_failed`, `EXPIRED` → `threads_container_expired`, timeout → `threads_processing_timeout`, all determined with zero `threads_publish` and the temporary object deleted; shutdown during polling → `interrupted` determined; `submitted.delegated_checks` contains `closed_gop` and `edit_lists`. **Signed URL lifetime** (research §14): assert, using only product constants (no magic numbers in the test), that `media_delivery.MIN_URL_TTL_SECONDS >= threads_gateway.PUBLISH_TIMEOUT_SECONDS + ThreadsPublishSettings().video_timeout + threads_publishing.URL_TTL_SAFETY_MARGIN_SECONDS`, so no valid `url_ttl_seconds` lets the URL expire while Meta may still fetch or process the media; and that the signed URL is generated only after the upload finished (upload time never consumes its lifetime)

### Implementation for User Story 3

- [X] T035 [US3] Extend `check`/`prepare` for videos in backend/app/threads_publishing.py: `probe_video_streams` + `moov_before_mdat` + `video_problems`; payload streams the original file (`video/mp4` or `video/quicktime`), `total_bytes` = file size, `delegated_checks` in `submitted`
- [X] T036 [US3] Extend `upload` for videos in backend/app/threads_publishing.py: container with `video_url`, video waits (≤ 5 min) plus the common minimum container age before `threads_publish`, `error_message` mapping of research §10

**Checkpoint**: texto, imagen y vídeo se publican con fakes; ejecutar la suite completa.

---

## Phase 6: User Story 4 - Ver el texto exacto y configurar las opciones de Threads (Priority: P1)

**Goal**: el usuario ve el texto final exacto con su validez y configura `alt_text` en
imagen/vídeo.

**Independent Test**: el texto mostrado coincide con el enviado al fake; textos inválidos se
rechazan sin truncar; `alt_text` solo en imagen/vídeo, persiste y respeta su límite; otras
plataformas no muestran opciones de Threads.

### Tests for User Story 4

- [X] T037 [P] [US4] Write frontend/src/components/ThreadsPublishOptions.test.tsx: exact final text (whitespace and line breaks preserved), length/links counters and limits, notices about link preview and topic tag, problems list, `alt_text` field only for image/video with save and 1000-char error, read-only when not editable, media delivery notice only for image/video
- [X] T038 [P] [US4] Extend frontend/src/components/PublicationDetail.test.tsx: Threads publications render `ThreadsPublishOptions` and `Publish now`; YouTube/Instagram publications never render Threads options; editing the text of a text publication reloads the options

### Implementation for User Story 4

- [X] T039 [P] [US4] Add `getThreadsOptions`/`saveThreadsOptions` to frontend/src/api.ts and the fake endpoints to frontend/src/test-fake-api.ts
- [X] T040 [US4] Create frontend/src/components/ThreadsPublishOptions.tsx (pattern of `InstagramPublishOptions.tsx`) and render it from frontend/src/components/PublicationDetail.tsx for `platform === "threads"` with the existing `onSaved` → publish-check reload

**Checkpoint**: texto y opciones visibles y editables en la interfaz.

---

## Phase 7: User Story 5 - Validar todo antes de cualquier efecto remoto (Priority: P1)

**Goal**: cada problema detectable falla en preflight sin subir media ni crear containers.

**Independent Test**: para cada condición, con fakes: la publicación no pasa a `publishing`,
cero subidas al proveedor, cero containers, error seguro.

### Tests for User Story 5

- [X] T041 [P] [US5] Write backend/tests/test_threads_preflight.py: inactive project/account; not connected; reconnect required; identity mismatch and missing permission (from `verify_identity`); credential store unavailable; missing/changed file; unsupported content; invalid text (length, links, empty `TEXT`); invalid stored `alt_text`; incompatible image (incl. animated WebP, oversize derivative); incompatible video and every missing mandatory ffprobe value; no ffprobe; media delivery not configured (image/video only, never for text); quota exhausted → `threads_publishing_limit_reached`; quota temporary failure → publishes with `quota_unavailable` warning and `quota_checked: false`; quota unexpected shape or 4xx → `502 threads_unexpected_response`; previous container `PUBLISHED` → `threads_already_published`; already publishing → `publication_in_progress`. For every failing case: status unchanged, no attempt, zero provider `put`, zero containers. Plus: `publish-check` lists the local Threads problems like YouTube/Instagram

### Implementation for User Story 5

- [X] T042 [US5] Close only the mappings/cases that T041 reveals as still missing after US1–US3 in `check`/`prepare` of backend/app/threads_publishing.py, so every case of T041 yields the code of contracts/api.md §4 (no new behaviour beyond research §6, §9, §11; if T041 already passes, T042 is satisfied without changes)

**Checkpoint**: preflight completo; suite completa en verde.

---

## Phase 8: User Story 6 - Publicación automática programada en Threads (Priority: P2)

**Goal**: el scheduler genérico publica una publicación Threads armada exactamente una vez,
sin código de Threads en el scheduler.

**Independent Test**: reloj inyectable y fakes: una ejecución `scheduled`; pausa → ninguna;
carrera manual/scheduler → una.

### Tests for User Story 6

- [X] T043 [P] [US6] Write backend/tests/test_threads_scheduler.py: due armed text, image and video publications run once with `trigger = scheduled` through `start_publication`; global pause blocks automatic starts but not `Publish now` nor running attempts; manual vs scheduler and two concurrent ticks start at most one attempt; the maximum automatic concurrency is respected; a Threads preflight failure at due time follows the Feature 007 behaviour (disarmed with `auto_publish_error`, no containers); a content-less scheduled publication never needs a file

### Implementation for User Story 6

- [X] T044 [US6] Conditional: if T043 reveals a regression, fix only the affected files (backend/app/threads_publishing.py or neutral content-optional paths of backend/app/publications.py / backend/app/automation.py; never Threads code in the scheduler or automation) and run T043 again; if T043 passes, T044 is satisfied without changes

**Checkpoint**: publicación programada funcionando con fakes.

---

## Phase 9: User Story 7 - Nunca publicar un duplicado (Priority: P2)

**Goal**: write-ahead, una sola llamada a `threads_publish`, ambigüedad, reconciliación y
recuperación tras reinicio en cada fase.

**Independent Test**: interrumpir en cada fase y comprobar estado final, determinado/ambiguo,
`threads_publish` ≤ 1 por container, sin listado de posts y media temporal limpiado o
pendiente.

### Tests for User Story 7

- [X] T045 [P] [US7] Write backend/tests/test_threads_ambiguity.py: write-ahead committed before the publish request (assert run phase and attempt stage inside the fake's publish hook); write-ahead commit failure → `internal_error` determined and no publish; inconclusive publish (timeout, transport, 5xx, 429, unexpected body) with the container later `PUBLISHED` → `published` without remote identity + `remote_identity_unavailable`; with any other status or failing reads → `threads_publish_uncertain`, `outcome_determined=False`, message with `@username`, UTC time and text start; explicit rejection + container not `PUBLISHED` → `threads_publish_failed` determined; explicit rejection + `PUBLISHED` → published without identity; `threads_publish` called at most once per container in every case; the post list endpoint is never requested
- [X] T046 [P] [US7] Write backend/tests/test_threads_reconcile.py: `publish-check`/`Publish now` on a failed uncertain Threads attempt read the original container once; `PUBLISHED` → publication `published`, attempt `succeeded` without identity, run `succeeded`, no new attempt or container; any other result → unchanged and `remote_check_required` without `confirm_remote_checked`; with confirmation a new attempt creates a new container only after the §11 read; runs without `publish_started_at` are never reconciled
- [X] T047 [P] [US7] Write backend/tests/test_threads_recovery.py: restart (generic `recover_interrupted_attempts`) after a crash in each phase (`preparing`, `delivering_media`, `creating_container` with and without stored container, `processing_container`, `publishing` before and after the publish request, `verifying_result`) → determined vs uncertain per `UNCERTAIN_STAGES`, pending temporary objects swept, no automatic resume, `published` never republished; scheduler never retries an uncertain publication

### Implementation for User Story 7

- [X] T048 [US7] Extend US7 coverage of the anti-duplicate behaviour already implemented in T025 (no first implementation here) in backend/tests/test_threads_ambiguity.py: additional ambiguity scenarios (each inconclusive error type combined with each container status sequence), container states between attempts (previous container `PUBLISHED`, `FINISHED`, `EXPIRED`, unknown to Meta with the research §11 read), and non-duplication on advanced paths (manual retry after `confirm_remote_checked`, scheduler never retrying uncertain publications, image/video attempts with media delivery); fix backend/app/threads_publishing.py only if one of these tests reveals a defect
- [X] T049 [US7] Implement `ThreadsPublisher.reconcile` in backend/app/threads_publishing.py per research §12 (phase in `publishing`/`verifying_result`/`failed`, `container_id` and `publish_started_at` set; one status read; only `PUBLISHED` returns a `Reconciliation`)
- [X] T050 [US7] Add a Meta manual-review block shared by Instagram and Threads (account, caption/text, time) in frontend/src/components/PublicationAttempts.tsx, keeping the Instagram texts, with a test case in frontend/src/components/PublicationAttempts.test.tsx

**Checkpoint**: garantías anti-duplicados probadas por fase; suite completa en verde.

---

## Phase 10: User Story 8 - Entender los fallos y la pérdida de conexión (Priority: P3)

**Goal**: errores seguros y comprensibles; credencial invalidada → `Reconnect required`;
errores temporales no cambian la conexión.

**Independent Test**: provocar cada categoría con fakes y comprobar código, mensaje, estado
de publicación y de conexión, sin respuestas crudas de Meta.

### Tests for User Story 8

- [X] T051 [P] [US8] Write backend/tests/test_threads_errors.py: token invalid / permission denied during container creation, polling or publish → connection `reconnect_required` via Feature 010 and determined failure; `ThreadsUnavailable` at any step → connection unchanged; link-limit rejection at container creation → `threads_text_invalid`; every error code of contracts/api.md §4 has a non-empty English message without Meta text; failed publication shows last error, determined/uncertain flag and attempt history with trigger
- [X] T052 [P] [US8] Write backend/tests/test_threads_publish_secrets.py: after text, image, video, ambiguous and failed runs (logging at DEBUG via `caplog`), the access token, signed URL, `X-Amz-*` values and provider secret never appear in the SQLite dump (incl. `threads_publish_runs`, `submitted`, `details`, `warnings`), logs, error messages or any JSON response; post ids are not logged

### Implementation for User Story 8

- [X] T053 [US8] Complete `_failure` mapping and reconnect marking (`mark_reconnect_required` in a new session) in backend/app/threads_publishing.py per research §16

**Checkpoint**: todas las historias completas; suite completa en verde.

---

## Phase 11: Polish & Cross-Cutting Concerns

- [X] T054 [P] Extend frontend/src/storage-safety.test.tsx with Threads publishing flows (text creation, options, publish, attempts): no tokens, signed URLs or provider data in `localStorage`/`sessionStorage`
- [X] T055 [P] Write docs/threads-publishing.md: text/image/video publishing, text composition (description + hashtags, title not sent), limits and conservative counting, link preview and topic-tag behaviour of Threads, `alt_text`, image policy (WebP → PNG, animated rejected), video local checks vs `delegated_checks`, quota policy (three cases, `threads_unexpected_response` as possible contract drift), wait per type, ambiguous results and reconciliation, permalink policy, media delivery reuse and `url_ttl_seconds` > processing time, no remote delete
- [X] T056 [P] Update README.md (Publishing to Threads section, link to docs/threads-publishing.md; Threads accounts doc no longer says nothing is published) and docs/threads-accounts.md
- [X] T057 Run the full checks of quickstart.md §1 (backend `pytest`, `ruff check`, `ruff format --check`, `mypy`; frontend `lint`, `format:check`, `typecheck`, `test`, `build`) and fix every failure
- [X] T058 Real validation per quickstart.md §2 with the connected Threads account, starting with the POST body encoding check (step 1) and respecting every stop condition; record results in quickstart.md §3 and delete the test posts manually in Threads

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; **bloquea** todas las historias.
- **US1 (Phase 3)**: depende de Foundational. Es la base del publisher (check/prepare/upload).
- **US2 (Phase 4)** y **US3 (Phase 5)**: dependen de US1 (amplían `prepare`/`upload` en el
  mismo archivo); entre sí, US3 después de US2 (mismo archivo).
- **US4 (Phase 6)**: depende de Foundational (backend de opciones) y de T027/T029 (tipos y
  detalle); independiente de US2/US3 en el frontend.
- **US5 (Phase 7)**: depende de US1–US3 (cubre imagen y vídeo).
- **US6 (Phase 8)** y **US7 (Phase 9)**: dependen de US1 (US7 también de US2 para la limpieza
  tras reinicio).
- **US8 (Phase 10)**: depende de US1–US3.
- **Polish (Phase 11)**: depende de todas las historias; T058 al final.

### Dentro de cada historia

Tests primero (deben fallar) → backend → frontend → checkpoint.

### Parallel Opportunities

- Phase 1: T002 en paralelo con T001.
- Phase 2: todos los tests T004–T009 en paralelo; T015, T016, T017 y T018 en paralelo tras
  T010–T014.
- US1: T021 ∥ T022; T027 en paralelo con el backend T023–T026.
- US2: T030 ∥ T031. US4: T037 ∥ T038 ∥ T039. US7: T045 ∥ T046 ∥ T047. US8: T051 ∥ T052.
- Polish: T054 ∥ T055 ∥ T056.
- Frontend (T027–T029, T037–T040, T050) puede avanzar en paralelo con US2/US3 del backend.

### Parallel example: Foundational tests

```text
T004 test_migrations.py (0010)
T005 test_publications_states.py (architecture)
T006 test_text_publications.py
T007 test_threads_gateway_publish.py
T008 test_threads_media.py
T009 test_threads_options.py
```

### Parallel example: User Story 1

```text
Backend:  T021 → T023 → T024 → T025 → T026
Frontend: T022 → T027 → T028 → T029
```

---

## Implementation Strategy

### MVP (User Story 1)

1. Phase 1 + Phase 2 (suite completa en verde, sin regresiones).
2. Phase 3: publicación de texto con write-ahead y una sola llamada a `threads_publish`.
3. **Parar y validar**: tests de US1 con fakes; opcionalmente, paso 1 y 2 del quickstart
   (codificación de los `POST` y texto real) antes de seguir con media.

### Incremental delivery

1. Texto (US1) → imagen (US2) → vídeo (US3): cada uno validable con fakes.
2. Opciones y texto visibles (US4) y preflight completo (US5).
3. Scheduler (US6) y garantías anti-duplicados completas (US7).
4. Errores (US8), seguridad, docs y validación real (Phase 11).

### Notas

- Commits pequeños en inglés al cerrar cada grupo coherente de tareas (solo cuando el usuario
  lo pida).
- Ninguna tarea añade opciones de la API de Threads, `auto_publish_text`, reutilización de
  containers, transcodificación ni búsqueda de posts recientes.
