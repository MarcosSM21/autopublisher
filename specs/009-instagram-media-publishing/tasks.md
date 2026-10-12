---

description: "Task list for real Instagram image and Reel publishing (Feature 009)"
---

# Tasks: Publicación real de imágenes y Reels en Instagram

**Input**: Design documents from `specs/009-instagram-media-publishing/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-070, SC-011). Ningún test usa Internet, Meta
real, el keyring real ni un proveedor cloud real: se usan `FakeMeta` (ampliado),
`FakeMediaDeliveryProvider`, `InMemoryCredentialStore`, `probe_video_streams` simulado y
`sleep` instantáneo. En cada historia los tests se escriben primero y deben fallar antes de
implementar.

**Organization**: tareas agrupadas por historia de usuario (US1–US7 de la spec). Código,
comentarios, mensajes de API/UI, README, docs y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes).
- **[Story]**: historia de usuario (US1–US7).

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`.
- Frontend: `frontend/src/`, `frontend/src/components/`.
- Comandos de backend desde `backend/` (`uv run …`); de frontend, desde `frontend/` (`npm …`).

## Reglas transversales (aplican a todas las tareas)

- **Protocolo Meta** (research §1, no inventar nada más): host `graph.instagram.com`,
  versión de la constante existente `GRAPH_API_VERSION` de `instagram_gateway.py` (no
  duplicarla). `<IG_ID>` = `InstagramConnection.instagram_user_id`.
  - Container imagen: `POST /v26.0/<IG_ID>/media` form: `image_url`, `caption` (omitido si
    vacío), `alt_text` (solo si no vacío), `is_ai_generated=true|false`, `access_token`.
  - Container Reel: `POST /v26.0/<IG_ID>/media` form: `media_type=REELS`, `video_url`,
    `caption`, `share_to_feed=true|false`, `is_ai_generated=true|false`, `access_token`.
  - Estado: `GET /v26.0/<CONTAINER_ID>?fields=status_code,status`.
  - Publicar: `POST /v26.0/<IG_ID>/media_publish` form: `creation_id`, `access_token` →
    `{"id": "<IG_MEDIA_ID>"}`.
  - Permalink: `GET /v26.0/<IG_MEDIA_ID>?fields=id,permalink`.
  - Cuota: `GET /v26.0/<IG_ID>/content_publishing_limit?fields=quota_usage,config` →
    `{"data": [{"quota_usage": n, "config": {"quota_total": n, "quota_duration": s}}]}`.
  - Los `POST` llevan los parámetros **en el cuerpo de formulario**, nunca en la query.
  - **Prohibido** consultar `GET /<IG_ID>/media` (lista de publicaciones) para identificar
    un post (research §11.5).
- **Anti-duplicados** (research §11–§12): write-ahead (`instagram_publish_runs.phase =
  'publishing'` + `publish_started_at`, commit; después `reporter.enter_finalizing()` debe
  devolver `True`) **antes** de `media_publish`; `media_publish` y la creación de container
  **nunca** se reintentan automáticamente; ante un resultado no concluyente solo se lee el
  `status_code` del container original (0, 5, 15, 30, 60 s): `PUBLISHED` → éxito **sin
  identidad remota** (`external_id`/`external_url` = `None`, aviso
  `remote_identity_unavailable`); **cualquier otro estado** (incluidos `ERROR`/`EXPIRED`),
  fallo de consulta o sin respuesta → `instagram_publish_uncertain` (`determined=False`) y
  `remote_check_required` antes de un nuevo intento manual. `ERROR`/`EXPIRED` solo son fallo
  determinado **antes** de invocar `media_publish`.
- **Reconciliación** (research §11b): antes de exigir `remote_check_required`,
  `publish-check` y `Publish now` intentan una lectura única del container original del
  último intento ambiguo; solo `PUBLISHED` cambia algo (→ `published` sin identidad remota);
  cualquier otro resultado mantiene la ambigüedad. Nunca `media_publish`, nunca containers
  nuevos, nunca lista de posts.
- **Progreso** (genérico): `progress = 1.0` solo para intentos `succeeded`; en otro caso
  como máximo `0.99`.
- **Orden éxito → limpieza** (FR-056): `persist_success` (resultado + `PUBLISHED` +
  `succeeded`) y **después** `publisher.release(...)`. Un fallo de limpieza solo añade el
  aviso `temporary_media_cleanup_failed`; nunca cambia estados.
- **Preflight** (FR-031a): solo se permiten credencial/renovación, lecturas a Meta (identidad,
  cuota, estado de containers previos) e inspección local. Antes de pasar el preflight
  **nunca** se sube nada al proveedor ni se crea un container.
- **Media temporal** (research §16–§17): clave aleatoria `<key_prefix><uuid4hex>/<uuid4hex>.<ext>`
  con fila `temporary_media_objects` confirmada **antes** de subir; bucket privado; URL
  prefirmada (`SecretUrl`, TTL de config, por defecto 3600 s) solo en memoria y en el cuerpo
  del `POST` a Meta; nunca en SQLite, logs, errores ni respuestas de la API.
- **Secretos**: token de Instagram, cabeceras `Authorization`, credenciales del proveedor, URLs
  prefirmadas, `X-Amz-*` y respuestas crudas de Meta nunca aparecen en SQLite, logs, mensajes
  de error, respuestas JSON ni almacenamiento del navegador. El media ID no se escribe en logs.
- **Errores**: `AppError`/`ConflictError` existentes y `PublishFailure(code, message,
  determined)`; códigos exactos de [contracts/api.md](contracts/api.md) (≤ 40 caracteres).
  Excepciones del gateway con `from None`.
- **Núcleo genérico**: `publishing.py`, `publications.py`, `scheduler.py` y `automation.py`
  nunca importan `app.instagram_*`, `app.media_delivery_s3` ni `boto3`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependencias, configuración local y fixtures base.

- [X] T001 Add `boto3` to `[project].dependencies` and `boto3-stubs[s3]` to the `dev` group in backend/pyproject.toml, then run `uv sync` (updates backend/uv.lock)
- [X] T002 [P] Add `media-delivery*.json` to .gitignore (next to the Instagram/Meta patterns) and verify `git check-ignore backend/data/media-delivery.json`
- [X] T003 [P] Add `get_media_delivery_file()` (env `AUTOPUBLISHER_MEDIA_DELIVERY_FILE`, default `BACKEND_DIR / "data" / "media-delivery.json"`) to backend/app/config.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: modelo de datos, cambios neutrales del núcleo, media delivery genérico y S3,
gateway de publicación, helpers de media/caption, opciones de Instagram (backend) y fakes.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta completar esta fase.

### Tests foundational (escribir primero)

- [X] T004 [P] Extend backend/tests/test_migrations.py: `0008` upgrade/downgrade round-trip; `publication_attempts.stage` accepts `processing`/`finalizing` and keeps existing rows; tables `instagram_publication_options`, `instagram_publish_runs`, `temporary_media_objects` with the CHECKs/indexes of data-model.md; downgrade succeeds when no attempt uses the new stages and aborts with a clear error, leaving the schema untouched, when one row uses `processing` or `finalizing` (data-model.md §7)
- [X] T005 [P] Extend the architecture test in backend/tests/test_publications_states.py: add `app.instagram_`, `app.media_delivery_s3` and `boto3` to `FORBIDDEN_PREFIXES` for `publishing`, `publications`, `scheduler`, `automation`; add a test that `app/media_delivery.py` imports no `app.instagram_*`/`app.youtube_*`
- [X] T006 [P] Write backend/tests/test_media_delivery.py: config loading/validation (missing file, non-https endpoint, empty keys, `key_prefix` not ending in `/`, starting with `/` or containing `..`, TTL outside 900–86400 → `MediaDeliveryNotConfigured`); `reserve` commits the row **before** `provider.put` is called (assert row visible from another session inside a provider hook); keys are random, under the prefix and contain no file name; `upload` retries 3 times on `MediaDeliveryFailed`; `release` marks `deleted_at` and on failure increments `cleanup_failures`; `sweep` deletes only rows with `deleted_at IS NULL` whose attempt is not running; `SecretUrl` repr/str never show the URL; `RedactMediaDeliverySecrets` removes `X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Security-Token`, `image_url=`, `video_url=` values and `AWS4-HMAC-SHA256` authorization headers
- [X] T007 [P] Write backend/tests/test_media_delivery_s3.py using `botocore.stub.Stubber` (no network): `put` sends `ContentType` and reports progress; `signed_get_url` returns an https URL for `get_object` with the configured TTL; `delete` is idempotent (404 ok); any `botocore` error becomes `MediaDeliveryFailed` with no original message
- [X] T008 [P] Write backend/tests/test_instagram_gateway_publish.py against `FakeMeta`: request shapes of research §1 (form bodies, no `image_url`/`video_url` in the URL, version from `GRAPH_API_VERSION`); parsing of container id, `status_code`, media id, permalink and quota (with and without `data`); error classification table of research §18 (`MetaPublishRejected(code, subcode)`, `MetaUnavailable`, `MetaTokenInvalid`, `MetaPermissionDenied`, `MetaUnexpectedResponse`); no exception text contains bodies, URLs or tokens
- [X] T009 [P] Write backend/tests/test_instagram_media.py: caption = `description_with_hashtags` (description, blank line, `#a #b`; no title); limits 2200 chars / 30 hashtags / 20 mentions → `instagram_caption_invalid` with value and limit, never truncated; images per research §2 (JPEG passthrough byte-identical ≤ 8 MiB; JPEG > 8 MiB, CMYK, aspect < 0.8 or > 1.91 (using EXIF-oriented size), animated WebP/PNG, any non-opaque pixel → `instagram_image_incompatible` naming the requirement; opaque RGBA/P/L/16-bit PNG and WebP → in-memory JPEG with same displayed size, ICC kept, original file unchanged; > 8 MiB after q95 → q90 4:2:0 retry → incompatible); Reels per research §3 using fake `VideoStreams` (each blocking rule, audio optional, `moov` after `mdat`, unverifiable when probe is `None`); `fingerprint` changes with caption/options/checksum
- [X] T010 [P] Write backend/tests/test_instagram_options.py: `GET/PUT /api/publications/{id}/instagram-options` per contracts/api.md (defaults, `media_kind`, exact caption and counters, `share_to_feed` only for reels default `true`, `alt_text` only for images ≤ 1000 and trimmed/empty→null, `instagram_option_not_applicable`, `validation_error`, `platform_not_supported`, not editable in `publishing`/`published`/`cancelled`, `media_delivery_configured` flag, `problems` list) and that no response contains provider config or URLs
- [X] T011 [P] Extend backend/tests/test_publish_recovery.py, backend/tests/test_publish_service.py and backend/tests/test_publish_upload.py (with `FakePublisher`): a running attempt left in `finalizing` is closed as `interrupted` with `outcome_determined=False`, in `processing` with `True`; `enter_finalizing()` returns False when the stage cannot be saved; `release` is called after `persist_success` and after `persist_failure`, exceptions in `release` are swallowed and returned warnings are appended without changing `status`; a `PublishOutcome` with `external_id=None` persists `succeeded` + `published` with null id/url; `reconcile_uncertain` calls `FakePublisher.reconcile` only for a `failed` publication whose latest attempt needs manual review, before `remote_check_required`, and a returned `Reconciliation` moves attempt → `succeeded` (determined, no error) and publication → `published` atomically (conditional UPDATE: no change if the publication is no longer `failed`), while `None` changes nothing; `progress` is ≤ 0.99 for `running` and `failed` attempts (bytes complete) and 1.0 only for `succeeded`; YouTube regression: `progress == 1` after a successful upload, `reconcile` returns `None`, behaviour unchanged

### Implementation foundational

- [X] T012 Add to backend/app/models.py: `AttemptStage.PROCESSING`/`FINALIZING`, `UNCERTAIN_STAGES`, updated `stage_valid` CHECK, and models `InstagramPublicationOptions`, `InstagramPublishRun` (+ `InstagramPublishPhase`, `InstagramMediaKind` StrEnums), `TemporaryMediaObject` exactly as data-model.md (no relationships from `Publication`)
- [X] T013 Create backend/migrations/versions/0008_instagram_publishing.py: upgrade batch-recreates `publication_attempts` with the new stage CHECK (pattern of `0005`) and creates the three tables with named constraints/indexes; downgrade per data-model.md §7: **first** count `publication_attempts` rows with `stage IN ('processing', 'finalizing')` and, if any, raise `RuntimeError` with a clear message before touching the schema (never map those stages to another value); otherwise drop `instagram_publish_runs`, `temporary_media_objects`, `instagram_publication_options` and batch-recreate `publication_attempts` with the original CHECK; cover both downgrade paths in T004
- [X] T014 Update the generic core in backend/app/publishing.py (and `attempt_to_read` in backend/app/publications.py): `ProgressReporter.attempt_id`, `enter_processing()`, `enter_finalizing() -> bool` (implemented in `_AttemptReporter` via `set_stage`); `Publisher.release(prepared, ctx, *, attempt_id, succeeded) -> list[dict[str, str]]` and `Publisher.reconcile(session, publication, attempt, ctx) -> Reconciliation | None` with `Reconciliation(published_at, outcome)`; `PublishOutcome.external_id/external_url: str | None`; `add_warnings(ctx, attempt_id, warnings)` touching only `warnings`; `reconcile_uncertain(session, publication, ctx, publishers)` + `persist_reconciled_success` (research §11b; conditional UPDATE, transition `failed → published` only here) called in `get_publish_check` and `start_publication` before `requires_remote_check`; `PublicationRunner._execute` calls `release` after persisting success (after `refresh_details`/`update_details`) or failure, catching any exception; `recover_interrupted_attempts` and the unexpected-exception path use `UNCERTAIN_STAGES`; `attempt_to_read` exposes `progress = 1.0` only for `succeeded` and `min(ratio, 0.99)` otherwise; neutral texts for `INTERRUPTED_REVIEW_MESSAGE`, `INTERNAL_ERROR_REVIEW_MESSAGE`, `RESULT_NOT_SAVED_MESSAGE` and `remote_check_required` (contracts/api.md); no Instagram import
- [X] T015 Move `_effective_metadata` → `effective_metadata(publication, content)` and `build_description` → `description_with_hashtags(description, hashtags)` into backend/app/publications.py, plus `ensure_not_publishing(session, account_id)` from youtube_connections.py; update imports in backend/app/youtube_publishing.py and backend/app/youtube_connections.py; add a no-op `release` returning `[]` and a `reconcile` returning `None` to `YouTubePublisher`, and programmable `release`/`reconcile` to `FakePublisher` in backend/tests/fakes.py
- [X] T016 [P] Create backend/app/media_delivery.py: `MediaDeliveryConfig`, `load_media_delivery_config(path)`, `MediaDeliveryNotConfigured`, `MediaDeliveryFailed`, `SecretUrl` (`reveal()`, hidden repr/str), `MediaDeliveryProvider` Protocol (`name`, `put`, `signed_get_url`, `delete`), `TemporaryMediaService(session_factory, provider_factory, clock)` with `reserve`/`upload`/`public_url`/`release`/`sweep` per research §16, `RedactMediaDeliverySecrets` and `install_media_delivery_log_redaction()` (HTTP loggers + `botocore`, `boto3`, `urllib3` set to WARNING)
- [X] T017 [P] Create backend/app/media_delivery_s3.py: `S3CompatibleProvider(config)` with boto3 (`endpoint_url`, `region_name`, keys, `signature_version="s3v4"`), `put` via `upload_fileobj` (bytes or file, `ContentType`, progress callback), `signed_get_url` via `generate_presigned_url("get_object", ExpiresIn=ttl)` wrapped in `SecretUrl`, idempotent `delete`; all botocore errors → `MediaDeliveryFailed` `from None`
- [X] T018 [P] Add `probe_video_streams(path) -> VideoStreams | None` (format name/size/duration/bit_rate; per-stream codec_type, codec_name, width, height, avg/r_frame_rate, pix_fmt, field_order, bit_rate, sample_rate, channels) and `moov_before_mdat(path) -> bool | None` (reads only top-level box headers) to backend/app/media.py; autouse stub in backend/tests/conftest.py returning `None` unless a test injects streams or uses `real_ffprobe`
- [X] T019 [P] Create backend/app/instagram_media.py (pure, no network): `build_caption`, `caption_stats`, `caption_problems`, `PreparedImage` + `prepare_image(path, media_format)` + `image_problems`, `reel_problems(path, size, streams, moov_first)`, `fingerprint(...)`, constants for all limits (research §2–§5)
- [X] T020 Extend backend/app/instagram_gateway.py: `MetaPublishRejected(code, subcode)` and subcode-aware `_error_for` (research §18), `create_image_container`, `create_reel_container`, `container_status`, `publish`, `media_permalink`, `publishing_limit` (returns `quota_usage`, `quota_total` or `None` if shape unexpected); POST form bodies; per-call timeout 60 s for container creation and `media_publish`
- [X] T021 Extend `FakeMeta` in backend/tests/fakes.py: endpoints `media` (create), container status (scripted sequences per container), `media_publish` (success, explicit errors, timeout/transport/5xx outcomes that still publish or not), media permalink, `content_publishing_limit`; recorded requests; counters of containers created and publishes executed; a request to the media **list** endpoint fails the test. Add `FakeMediaDeliveryProvider` (in-memory objects, scripted put/delete failures, hooks, records whether each signed URL was "fetched")
- [X] T022 Add `InstagramPublicationOptionsRead`/`Write` schemas (contracts/api.md, `extra="forbid"`) to backend/app/schemas.py and the `GET/PUT /api/publications/{publication_id}/instagram-options` router with `get_options`/`options_to_read` (no network, uses `instagram_media` and `load_media_delivery_config` only to report problems) in new backend/app/instagram_publishing.py
- [X] T023 Wire in backend/app/main.py: `create_app(..., media_delivery_provider=None, instagram_publish_settings=None)`; build `TemporaryMediaService` (provider from config on demand, or the injected fake); register `instagram_publishing.router`; call `install_media_delivery_log_redaction()`; after `recover_interrupted_attempts`, run `sweep()` in a daemon thread (errors only logged); fixtures `media_delivery_file`, `fake_media_delivery`, `instagram_publication` (connected account + image/video content) in backend/tests/conftest.py

**Checkpoint**: migración, núcleo extendido, media delivery, gateway, opciones y fakes listos;
`uv run pytest` en verde (incluidos YouTube y scheduler existentes).

---

## Phase 3: User Story 1 - Publicar ahora una imagen en Instagram (Priority: P1) 🎯 MVP

**Goal**: `Publish now` publica una imagen (JPEG tal cual o PNG/WebP convertida en memoria)
en el feed y guarda media ID y permalink; después se limpia el media temporal.

**Independent Test**: con fakes, publicación de imagen de una cuenta `Connected` con
AI-generated declarado → `published`, intento `succeeded` (`manual`), media ID y permalink,
objeto temporal borrado tras el éxito, original idéntico y sin secretos.

### Tests for User Story 1

- [X] T024 [P] [US1] Write backend/tests/test_instagram_publish.py (image part): JPEG and PNG end-to-end; stages `preparing → uploading → processing → finalizing → done`; `instagram_publish_runs` phases; one container and one `media_publish`; the signed URL was sent only in the POST body; `submitted` snapshot of data-model.md; `external_id`/`external_url` = media id/permalink; permalink failure → profile URL + `permalink_unavailable`; original file sha256 unchanged; progress never 1.0 before success
- [X] T025 [P] [US1] Write backend/tests/test_instagram_cleanup.py: `release` runs only after `persist_success` (assert status already `published` inside the provider delete hook); delete failure → `published`/`succeeded` unchanged, warning `temporary_media_cleanup_failed`, row pending and removed by a later `sweep`; cleanup after determined failures
- [X] T026 [P] [US1] Write frontend/src/components/PublicationAttempts.test.tsx (and extend PublicationDetail.test.tsx / PublicationQueue.test.tsx): `Open on Instagram` for Instagram attempts and `Open on YouTube` for YouTube; phase labels for `processing`/`finalizing`; percent only during `uploading`, capped at 99 % while running; cleanup warning shown without changing the status badge; no link when `external_url` is null

### Implementation for User Story 1

- [X] T027 [US1] Implement `InstagramPublisher.check` in backend/app/instagram_publishing.py (no network): media kind, file availability/size, `image_problems`/`reel_problems`, caption, options (`instagram_options_incomplete`), `media_delivery_not_configured` (503), connection state (`instagram_not_connected`/`instagram_reconnect_required`), and the summary rows of contracts/api.md
- [X] T028 [US1] Implement `InstagramPublisher.prepare` for the base path in backend/app/instagram_publishing.py: `verify_identity` from instagram_connections (credential, identity, Professional), build `InstagramPayload` (bytes for converted JPEG or original path, content type, size, caption, options, fingerprint) and `PreparedPublication` with `total_bytes` = delivered size and the `submitted` snapshot
- [X] T029 [US1] Implement `InstagramPublisher.upload` happy path for images in backend/app/instagram_publishing.py: create run (`preparing`) → `delivering_media` + `TemporaryMediaService.reserve/upload` with `reporter.report_bytes` → `public_url` → `reporter.enter_processing()` + `creating_container` (commit before the call, store `container_id`/`container_created_at` right after) → `processing_container` polling with `InstagramPublishSettings` (2, 5, 10, 20, 30, then 60 s; 5 min images; `should_stop`) → write-ahead (`publishing`, `publish_started_at`, `enter_finalizing()`) → `publish` → `verifying_result` + permalink (3 tries) → `succeeded` → `PublishOutcome`
- [X] T030 [US1] Implement `InstagramPublisher.release` and `refresh_details` in backend/app/instagram_publishing.py: delete the attempt's temporary objects via `TemporaryMediaService.release`, then `sweep()`; return `temporary_media_cleanup_failed` on failure; `refresh_details` retries the permalink once and stores it in `details.permalink`
- [X] T031 [US1] Register `Platform.INSTAGRAM: InstagramPublisher(gateway=..., credential_store=app.state.instagram_credential_store, media_delivery=..., settings=...)` in backend/app/main.py
- [X] T032 [P] [US1] Update frontend/src/types.ts (`AttemptStage` with `processing`/`finalizing`, nullable `external_id`/`external_url`) and add `platformName()` / `attemptPhaseLabel()` in frontend/src/utils.ts
- [X] T033 [US1] Update frontend/src/components/PublicationAttempts.tsx and frontend/src/components/PublicationQueue.tsx: platform-aware `Open on …`, phase labels, percent only in `uploading` (≤ 99 % while running), warnings list; make `publishable` in frontend/src/components/PublicationDetail.tsx true for `youtube` and `instagram`; extend frontend/src/test-fake-api.ts with Instagram attempts and stages

**Checkpoint**: una imagen se publica de extremo a extremo con fakes y la interfaz muestra el
resultado.

---

## Phase 4: User Story 2 - Publicar ahora un vídeo como Reel (Priority: P1)

**Goal**: un vídeo compatible se publica como Reel tras esperar a `FINISHED`; estados
terminales y timeout fallan sin `media_publish`.

**Independent Test**: con fakes, container `IN_PROGRESS` varias consultas → `FINISHED` →
publicado; `ERROR`/`EXPIRED`/timeout → `failed` determinado, sin `media_publish`, objeto borrado.

### Tests for User Story 2

- [X] T034 [P] [US2] Extend backend/tests/test_instagram_publish.py (Reel part): `media_type=REELS`, `video_url`, explicit `share_to_feed` (default true, false when set) and `is_ai_generated`; streaming upload progress; polling intervals and 10 min timeout with the fake sleep (no busy loop; total sleeps bounded); `ERROR` → `instagram_processing_failed`, `EXPIRED` → `instagram_container_expired`, timeout → `instagram_processing_timeout`, all determined, zero `media_publish` calls, temporary object deleted; shutdown during polling → determined failure
- [X] T035 [P] [US2] Add Reel preflight cases to backend/tests/test_instagram_preflight.py: each incompatible stream property and WebM, missing ffprobe → `instagram_media_unverifiable`, with zero provider uploads and zero containers

### Implementation for User Story 2

- [X] T036 [US2] Extend `check`/`prepare` in backend/app/instagram_publishing.py for videos: `probe_video_streams` + `moov_before_mdat` + `reel_problems`; payload streams the original file (`video/mp4` or `video/quicktime`), `total_bytes` = file size
- [X] T037 [US2] Extend `upload` in backend/app/instagram_publishing.py for Reels: reel container params, 10 min polling limit, terminal states mapping and `stop` handling (research §8)

**Checkpoint**: imágenes y Reels se publican con fakes.

---

## Phase 5: User Story 3 - Configurar caption y opciones de Instagram (Priority: P1)

**Goal**: el usuario ve el caption exacto y configura AI-generated, `share_to_feed` (Reel) y
`alt_text` (imagen) antes de publicar o programar.

**Independent Test**: el caption mostrado coincide con el enviado al fake; AI-generated
obligatorio; `alt_text` solo en imágenes y `share_to_feed` solo en Reels; persistencia tras
reiniciar; nada de esto aparece en otras plataformas.

### Tests for User Story 3

- [X] T038 [P] [US3] Write frontend/src/components/InstagramPublishOptions.test.tsx: `Image Post`/`Reel`, exact caption with counters and limit errors, AI-generated Yes/No required, `Share to feed` only for Reels (checked by default, explained), `Alt text` only for images with 1000 counter, problems list (incompatible media, delivery not configured), read-only when not editable, save calls the API
- [X] T039 [P] [US3] Extend frontend/src/components/PublicationDetail.test.tsx: the Instagram panel appears only for Instagram publications and the YouTube panel only for YouTube; saving options reloads the publish check
- [X] T040 [P] [US3] Extend backend/tests/test_instagram_publish.py: caption sent to Meta equals `GET instagram-options.caption` character by character; `alt_text` absent when empty and never sent for Reels; title never sent; options persist across an app restart (new `TestClient` on the same DB)

### Implementation for User Story 3

- [X] T041 [P] [US3] Add Instagram option types and `getInstagramOptions`/`saveInstagramOptions` to frontend/src/types.ts and frontend/src/api.ts; support them in frontend/src/test-fake-api.ts
- [X] T042 [US3] Create frontend/src/components/InstagramPublishOptions.tsx per plan (labels in English, no browser storage)
- [X] T043 [US3] Mount `InstagramPublishOptions` in frontend/src/components/PublicationDetail.tsx when `platform === "instagram"` (neutral extension point next to the YouTube panel) and bump `checkVersion` on save

**Checkpoint**: P1 completo (imagen, Reel, opciones y caption).

---

## Phase 6: User Story 4 - Validar todo antes de cualquier efecto remoto de publicación (Priority: P1)

**Goal**: toda condición detectable falla en preflight sin subir nada ni crear containers;
solo lecturas seguras permitidas.

**Independent Test**: para cada condición, publicación no pasa a `publishing`, el fake del
proveedor no recibe `put` y `FakeMeta` no recibe `media`/`media_publish`.

### Tests for User Story 4

- [X] T044 [P] [US4] Write backend/tests/test_instagram_preflight.py (general part): inactive project/account, non-Instagram account, `Not connected`, `Reconnect required`, missing credential, identity mismatch, not Professional, missing/changed file, unsupported content, image incompatibilities, caption invalid, options incomplete, delivery not configured (503), quota reached (`quota_usage >= quota_total`), quota read failure → continues with `quota_checked: false`, execution already running; in every case zero `put`, zero containers, zero `media_publish`; allowed reads (refresh, `/me`, quota) may have happened
- [X] T045 [P] [US4] Extend backend/tests/test_instagram_options.py / publish-check tests: `GET /publish-check` lists Instagram problems and summary without any network call (assert `FakeMeta.requests` empty) whenever the latest attempt is not an ambiguous Instagram attempt with a known container (the only reconciliation case, covered by T053)

### Implementation for User Story 4

- [X] T046 [US4] Add the quota check to `prepare` in backend/app/instagram_publishing.py (`instagram_publishing_limit_reached`; temporary/unexpected read → continue and record `quota_checked: false`), map `verify_identity` / credential `AppError`s unchanged, and keep the error order of contracts/api.md
- [X] T047 [US4] Add `ensure_not_publishing(session, account_id)` to the Instagram disconnect route in backend/app/instagram_connections.py (+ case in backend/tests/test_instagram_disconnect.py)

**Checkpoint**: ningún fallo de preflight produce efectos remotos de publicación ni de delivery.

---

## Phase 7: User Story 5 - Publicación automática programada en Instagram (Priority: P2)

**Goal**: el scheduler genérico ejecuta publicaciones Instagram armadas exactamente una vez.

**Independent Test**: reloj inyectable + fakes: una ejecución `scheduled`; pausa bloquea;
manual vs scheduler y ciclos concurrentes → un solo container y un solo `media_publish`.

### Tests for User Story 5

- [X] T048 [US5] Write backend/tests/test_instagram_scheduler.py (edge cases): Instagram preflight failure at due time follows Feature 007 behaviour (no `publishing`, no upload, no container, visible reason); an ambiguous `failed` Instagram publication is never picked by the scheduler; a `published` one is never executed again
- [X] T049 [US5] Extend backend/tests/test_instagram_scheduler.py (functional scheduled execution, no import checks — those live in T005): an armed due Instagram publication runs exactly once through the generic scheduler/executor with `trigger=scheduled` (one container, one `media_publish`); paused automation skips it while `Publish now` still works and a running Instagram attempt is not cancelled; `Publish now` racing a tick and two concurrent ticks start a single attempt

### Implementation for User Story 5

- [X] T050 [US5] Verify and complete only the wiring that lets a scheduled Instagram publication reach its publisher through the existing generic infrastructure: `Platform.INSTAGRAM` resolves to the `InstagramPublisher` instance in `app.state.publishers` built in backend/app/main.py (same mapping the `Scheduler` receives), and `InstagramPublisher.check`/`prepare` in backend/app/instagram_publishing.py work with the scheduler's `start_publication(..., trigger=AttemptTrigger.SCHEDULED)` call (no HTTP-only dependencies); no change to backend/app/scheduler.py, no Instagram-specific code in backend/app/publishing.py, no second scheduler; manual vs scheduled races stay protected by the generic conditional claim and the unique running-attempt index

**Checkpoint**: publicación programada de Instagram con el scheduler genérico.

---

## Phase 8: User Story 6 - Nunca publicar un duplicado (Priority: P2)

**Goal**: write-ahead, resultado no concluyente sin repetición, publicación confirmada sin
identidad remota, bloqueo de duplicados entre intentos, recuperación tras reinicio y
limpieza crash-safe.

**Independent Test**: con fakes, interrupción/fallo en cada fase; nunca más de un
`media_publish` por container ni búsqueda de posts recientes.

### Tests for User Story 6

- [X] T051 [P] [US6] Write backend/tests/test_instagram_ambiguity.py: write-ahead committed before the publish request (assert in a `FakeMeta` hook that the run is `publishing` and the attempt `finalizing`); `enter_finalizing` failure → no publish, determined failure; timeout/transport/5xx/Graph 1–2 on `media_publish` followed by container `PUBLISHED` → `published`, `succeeded`, `outcome_determined=True`, null id/url, warning `remote_identity_unavailable`; followed by `ERROR` → still ambiguous (`instagram_publish_uncertain`, `outcome_determined=False`); followed by `EXPIRED` → still ambiguous; followed by `FINISHED`/`IN_PROGRESS`/unknown value/unreachable → still ambiguous; for every ambiguous case a new `POST /publish` without `confirm_remote_checked` returns `remote_check_required` (after a reconciliation read that does not confirm `PUBLISHED`) and only with `confirm_remote_checked=true` can a new attempt start; explicit 4xx + container `PUBLISHED` → published without identity; explicit 4xx + not published → determined failure with mapped code; in all cases exactly one `media_publish`, no second container, and zero requests to the media list endpoint
- [X] T052 [P] [US6] Write backend/tests/test_instagram_recovery.py: restart (new app on same DB) with the attempt in `preparing`, `uploading`, `processing` → `failed` determined and the object swept; in `finalizing` → `failed` ambiguous with no Meta call at startup (reconciliation only happens later, T053); after a reconciliation that does not confirm `PUBLISHED`, a retry with `confirm_remote_checked` and a previous container that later reads `PUBLISHED` in `prepare` → `instagram_already_published` with no new effects (defense in depth); previous container `FINISHED` with same fingerprint → reused (no upload, no new container, one publish); different fingerprint or `ERROR`/`EXPIRED`/older than 23 h → new container; status read failure → `instagram_unavailable` without effects; crash between `reserve` and `put` leaves a row that `sweep` resolves; `published` publications are never executed again
- [X] T053 [P] [US6] Write backend/tests/test_instagram_reconcile.py (research §11b, contracts/api.md): ambiguous attempt (`finalizing`/run `publishing` with `container_id`) + container `PUBLISHED` → `GET /publish-check` and, separately, `POST /publish` without `confirm_remote_checked` reconcile it with no confirmation (including the timeout + later `PUBLISHED` case): publication `published` with `published_at` = the run's `publish_started_at`, original attempt `succeeded` + determined, `external_id`/`external_url` null, warning `remote_identity_unavailable`, `requires_remote_check=false`, `publish` returns `publication_not_eligible`, no new attempt; ambiguous + container `FINISHED`/`IN_PROGRESS`/`ERROR`/`EXPIRED`/Meta unavailable/credential unusable → nothing changes, `requires_remote_check=true` and `remote_check_required` without confirmation; run without `container_id` or not in the final phase → no Meta call; one status read per request (no polling loop); in every case zero extra `media_publish` calls, zero containers created and zero requests to the media list endpoint; YouTube ambiguous attempts are not reconciled

### Implementation for User Story 6

- [X] T054 [US6] Implement the inconclusive/explicit-error handling of `media_publish` in backend/app/instagram_publishing.py exactly as research §11 (read-only container polls 0/5/15/30/60 s; only `PUBLISHED` resolves, any other status including `ERROR`/`EXPIRED`, unknown values or read failures → `instagram_publish_uncertain` with `determined=False`; `PublishOutcome(external_id=None, external_url=None, warnings=[remote_identity_unavailable])`; uncertain message includes `@username`, write-ahead time and caption; never list recent media)
- [X] T055 [US6] Implement in backend/app/instagram_publishing.py: `InstagramPublisher.reconcile` (research §11b: requires the attempt to still be ambiguous (`failed` + `outcome_determined = false`) and its run in `publishing`, `verifying_result` or `failed` (the usual phase after an ambiguous result) with `container_id`; one `status_code` read with a valid credential; `PUBLISHED` → `Reconciliation(run.publish_started_at, PublishOutcome(None, None, [remote_identity_unavailable]))` and run `succeeded`; anything else → `None`); the previous-run check of research §12 in `prepare` (latest run with `container_id` < 23 h → read status → `instagram_already_published` / reuse with `container_reused: true`, `reused_from_attempt_id` / new); and the reuse path in `upload` (`preparing → finalizing`, no delivery, no container creation)

**Checkpoint**: 0 duplicados en todos los escenarios simulados.

---

## Phase 9: User Story 7 - Entender los fallos y la pérdida de conexión (Priority: P3)

**Goal**: cada categoría de error tiene código y mensaje seguros; credencial invalidada →
`Reconnect required`; temporales nunca.

**Independent Test**: provocar cada código de contracts/api.md con fakes y comprobar mensaje,
estado de publicación, estado de conexión y ausencia de datos crudos.

### Tests for User Story 7

- [X] T056 [P] [US7] Write backend/tests/test_instagram_errors.py: every execution code of contracts/api.md (`media_delivery_failed`, `instagram_container_failed`, `instagram_media_fetch_failed`, `instagram_media_rejected`, `instagram_publishing_limit_reached`, `instagram_account_restricted`, `instagram_reconnect_required`, `instagram_unavailable`, `instagram_publish_failed`, …) with `determined` as specified; Graph 190 / permission during execution → connection `reconnect_required`; transport/5xx/429 → connection stays `connected`; messages contain none of `FAKE_META_ERROR_TEXT`, tokens, URLs or media ids
- [X] T057 [P] [US7] Write backend/tests/test_instagram_publish_secrets.py: after image, Reel, failure and ambiguous runs, SQLite dump, captured logs (all levels, HTTP and botocore loggers) and every API response contain no Instagram token, provider secret/access key, signed URL, `X-Amz-Signature`/`X-Amz-Credential`, raw Meta text or (in logs) media id
- [X] T058 [P] [US7] Extend frontend/src/storage-safety.test.tsx to cover `InstagramPublishOptions` and Instagram attempts (no `localStorage`/`sessionStorage`)

### Implementation for User Story 7

- [X] T059 [US7] Complete the error mapping in backend/app/instagram_publishing.py (research §18): gateway exceptions → `PublishFailure` codes/messages; every terminal `PublishFailure` (and any unexpected exception) first sets the attempt's `instagram_publish_runs.phase = 'failed'` with the last known `container_status`, keeping only safe codes; call `mark_reconnect_required` (Feature 008) on token/permission errors during execution; bounded retries only for idempotent reads and provider upload
- [X] T060 [US7] Frontend failure and reconciliation display: in frontend/src/components/PublicationAttempts.tsx show attempt error code/message, determined vs manual review and trigger origin for Instagram (reusing the existing YouTube rendering); in frontend/src/components/PublicationDetail.tsx, after each `publish-check` load, if `requires_remote_check` differs from the previous value or the publication is no longer eligible for `Publish now` because of a reconciliation, re-fetch `GET /publications/{id}` and call `onChanged()` so detail, status badge, attempts, `remote_identity_unavailable` warning, available actions and the `Publish now` button refresh (no polling of `publish-check`); support reconciliation in frontend/src/test-fake-api.ts and add a test in frontend/src/components/PublicationDetail.test.tsx: `failed` ambiguous Instagram publication → `publish-check` reconciles → detail shows `Published`, no `Publish now` and the warning, without a manual reload

**Checkpoint**: todas las historias funcionales y probadas con fakes.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T061 [P] Write docs/instagram-publishing.md: R2 **private** bucket, scoped token (Object Read & Write on the dedicated bucket/prefix), `media-delivery.json` (placeholders only), **mandatory lifecycle rule** on the exclusive prefix (dashboard steps + JSON, ~48 h max), presigned URL TTL (temporary access only through the signed, expiring URL), explicit constraints (anonymous Quick Tunnels are not a supported production solution; AutoPublisher never creates or keeps a permanent public copy), image/Reel requirements and conversion policy, caption and options, ambiguous results, automatic reconciliation and `remote_identity_unavailable` (manual profile check), cleanup warnings, App Review/Development Mode, deleting test posts manually; note that moving the Secret Access Key to the OS secure store is possible future hardening
- [X] T062 [P] Update README.md with a "Publishing to Instagram" section linking docs/instagram-publishing.md and the configuration file
- [X] T063 Run backend checks from backend/: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; fix failures
- [X] T064 Run frontend checks from frontend/: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, `npm run build`; fix failures
- [X] T065 Run the real validation of specs/009-instagram-media-publishing/quickstart.md §2 (R2 + lifecycle, image, Reel, preflight rejections, scheduler, secrets, crash cleanup) and record in the PR description the blocking checks (presigned URL accepted, `<IG_ID>`, quota shape, container fields) and the measured time from confirming `Publish now` of a valid image to `Published` (target < 1 min under normal conditions; validation metric, not a functional timeout)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; **bloquea** todas las historias.
- **US1 (Phase 3)**: depende de Foundational. MVP.
- **US2 (Phase 4)**: depende de US1 (mismo publisher; añade la rama de vídeo).
- **US3 (Phase 5)**: depende de Foundational (API de opciones); T040 usa el flujo de US1.
- **US4 (Phase 6)**: depende de US1 (`check`/`prepare`); los casos de Reel de T035 dependen de US2.
- **US5 (Phase 7)**: depende de US1.
- **US6 (Phase 8)**: depende de US1 (y de US2 para casos de Reel).
- **US7 (Phase 9)**: depende de US1, US2 y US6.
- **Polish (Phase 10)**: depende de todas las historias deseadas.

### Within Each User Story

- Tests primero (deben fallar) → backend → tipos/API cliente → componentes.
- Las tareas sobre backend/app/instagram_publishing.py son secuenciales entre sí (mismo
  archivo): T022 → T027 → T028 → T029 → T030 → T036 → T037 → T046 → T054 → T055 → T059.
- T014 antes de T015 (ambas tocan el contrato del publisher); T012 → T013.
- T048 → T049 (mismo archivo `backend/tests/test_instagram_scheduler.py`; no son paralelas).

### Parallel Opportunities

- Setup: T002 y T003.
- Foundational: tests T004–T011 en paralelo; tras T012/T014, T016, T017, T018 y T019 en
  paralelo; T020 y T021 en paralelo.
- US1: T024, T025, T026 en paralelo; T032 en paralelo con el backend.
- US3: T038–T041 en paralelo.
- US4–US7: los archivos de test de cada historia en paralelo.
- Polish: T061 y T062.

---

## Parallel Example: Foundational

```text
T004 test_migrations · T005 arquitectura · T006 test_media_delivery · T007 test_media_delivery_s3
T008 test_instagram_gateway_publish · T009 test_instagram_media · T010 test_instagram_options
# después de T012/T014:
T016 media_delivery.py · T017 media_delivery_s3.py · T018 media.py · T019 instagram_media.py
```

## Parallel Example: User Story 1

```text
T024 backend/tests/test_instagram_publish.py
T025 backend/tests/test_instagram_cleanup.py
T026 frontend PublicationAttempts/Detail/Queue tests
T032 frontend/src/types.ts + utils.ts
```

## Parallel Example: User Story 6

```text
T051 backend/tests/test_instagram_ambiguity.py
T052 backend/tests/test_instagram_recovery.py
T053 backend/tests/test_instagram_reconcile.py
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1 + Phase 2.
2. US1 → imagen publicada con fakes, limpieza posterior al éxito.
3. **Parar y validar**: quickstart §1 y §2 pasos 1–3 (incluida la regla de lifecycle y las
   comprobaciones bloqueantes: URL prefirmada aceptada, `<IG_ID>`, forma de la cuota). Si
   Meta no acepta la URL prefirmada, revisar research §17 antes de seguir.

### Incremental Delivery

1. MVP (US1).
2. US2 (Reels) y US3 (opciones/caption en la UI).
3. US4 (preflight completo).
4. US6 (anti-duplicados) — recomendable antes de usar el scheduler con cuentas reales.
5. US5 (scheduler).
6. US7 (errores y secretos).
7. Polish: documentación, checks y validación real completa.

---

## Notes

- Fuera de alcance: carousels, Stories, varios archivos, tags, ubicación, música,
  colaboraciones, transcodificación, edición o borrado remoto, búsqueda automática de posts.
- Los posts de prueba reales se borran a mano desde Instagram.
- Commits pequeños en inglés por tarea o grupo lógico, solo cuando el usuario lo pida.
