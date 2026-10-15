---

description: "Task list for TikTok Upload to Inbox (Feature 014)"
---

# Tasks: TikTok Upload to Inbox

**Input**: Design documents from `specs/014-tiktok-inbox-upload/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige (FR-043). Offline: `FakeTikTok` ampliado, `InMemoryCredentialStore`,
`FakeClock`, `sleep` instantáneo, `probe_video_streams` simulado, archivos pequeños con
`chunk_size` inyectable. En cada fase funcional los tests se escriben **primero** y deben fallar
antes de implementar. Durante el desarrollo, solo tests dirigidos
(`uv run pytest tests/test_tiktok_….py`, `npm test -- TikTok`); regresiones afectadas cuando se
toca código compartido (T017, T021); suite completa solo en T068 y en CI.

**Organization**: fases según plan.md (scopes → V1a → foundation → Inbox mínimo → V1b → Bloque 2
→ V2), con etiquetas de historia de la spec. Código, comentarios, mensajes de API/UI, README,
docs y commits en inglés.

> ## ⛔ Límites de `/speckit-implement`
>
> 1. **Detenerse en T010 (V1a)**: validación manual de Reconnect con tres scopes que ejecuta el
>    usuario. Continuar solo con PASS registrado en `quickstart.md → Resultados`.
> 2. **Detenerse en T039 (V1b)**: envío real al inbox con la cuenta **pública**. Continuar con
>    T040 solo con PASS. Si TikTok exige cuenta privada, audit u otra condición: STOP y revisar
>    spec/plan.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivo distinto, sin dependencias pendientes).
- **[Story]**: US1 V1 real · US2 modo + Send to TikTok · US3 scopes · US4 scheduler · US5 Check
  status · US6 anti-duplicados/reinicio · US7 errores · US8 multi-chunk.

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/` (desde `backend/`
  con `uv run …`).
- Frontend: `frontend/src/`, `frontend/src/components/` (desde `frontend/`).

## Reglas transversales

- **Alcance**: solo vídeo, `FILE_UPLOAD`, `inbox/video/init/` con **solo `source_info`**.
  Prohibido: `post_info` en Inbox, `video.list`, listar posts, webhooks, `PULL_FROM_URL`, fotos,
  automatización móvil, scraping, borrado remoto, contador local de envíos pendientes.
- **Endpoints**: `POST {TIKTOK_API_HOST}/v2/post/publish/inbox/video/init/` (nuevo),
  `PUT {upload_url}`, `POST /v2/post/publish/status/fetch/` (existente).
- **Anti-duplicados**: init Inbox ≤ 1 por intento; `publish_id` commit antes del primer byte;
  write-ahead antes del último chunk; último chunk exactamente una vez; nunca un nuevo upload
  automático (ni por espera del usuario, reinicio, ni `SEND_TO_USER_INBOX` prolongado).
- **Estado genérico** `AWAITING_USER_ACTION`: terminal para la ejecución, no para la
  publicación; el intento de entrega `succeeded` **nunca** se reescribe; `Check status` nunca
  crea intentos.
- **Scopes**: base = `user.info.basic` + `video.publish`; `video.upload` = capacidad. Su
  ausencia nunca produce `Reconnect required`.
- **Secretos**: `upload_url`, tokens, `Authorization`, `publish_id` y respuestas crudas nunca en
  DB, logs, API, errores ni navegador.
- **Núcleo neutral**: `publishing.py`, `publications.py`, `scheduler.py`, `automation.py` sin
  ninguna referencia a TikTok.

---

## Phase 1: Setup

- [X] T001 Extend `FakeTikTok` in backend/tests/fakes.py: `inbox_init` endpoint (records request bodies so tests can assert no `post_info`), programmable status `SEND_TO_USER_INBOX`, error code `spam_risk_too_many_pending_share` (403), `scope_not_authorized` for `video.upload`, and configurable granted scopes for token exchange and refresh (default: the three requested scopes)
- [X] T002 [P] Add fixtures in backend/tests/conftest.py: TikTok connection with base scopes only, with the three scopes, and a TikTok video publication factory with `mode` parameter (`None`, `DIRECT_POST`, `INBOX_UPLOAD`)

---

## Phase 2: User Story 3 — Ampliar la conexión a `video.upload` (Priority: P1) 🎯 V1a

**Goal**: Connect/Reconnect piden tres scopes; scopes base mantienen la conexión; `video.upload`
es una capacidad.

**Independent Test**: con fakes de OAuth, Reconnect concede tres → `Connected` con
`inbox_upload: true`; Reconnect parcial → falla y la conexión previa de dos scopes queda
intacta; refresh sin `video.upload` → `Connected`, `inbox_upload: false`; refresh sin
`video.publish` → reglas de 012.

### Tests (write first)

- [X] T003 [P] [US3] Write backend/tests/test_tiktok_scopes.py: authorization URL requests `user.info.basic,video.publish,video.upload`; callback with three scopes connects with `capabilities = {direct_post: true, inbox_upload: true}`; callback missing `video.upload` fails with `tiktok_permission_missing` and an existing two-scope connection keeps its secret, row, identity and `connected` status byte-for-byte; existing two-scope connection reads `Connected` with `inbox_upload: false` and is usable by `get_valid_credentials`; refresh losing only `video.upload` stores the credential, stays `Connected`, capability false; refresh losing `video.publish` keeps Feature 012 behaviour (`reconnect_required`); `TikTokScopeMissing` keeps `video.upload` as scope name
- [X] T004 [P] [US3] Update expectations in backend/tests/test_tiktok_connect.py and backend/tests/test_tiktok_tokens.py that assume exactly two requested scopes (requested list, "grant both permissions" message) without weakening any existing assertion on base-scope rules

### Implementation

- [X] T005 [US3] In backend/app/tiktok_oauth.py split `SCOPES` into `BASE_SCOPES`, `UPLOAD_SCOPE`, `REQUESTED_SCOPES`, `KNOWN_SCOPES` (research §2); `build_authorization_url` uses `REQUESTED_SCOPES`; keep `REQUIRED_SCOPES = frozenset(BASE_SCOPES)` for renewal semantics
- [X] T006 [US3] In backend/app/tiktok_gateway.py add `TikTokCredential.has_requested_scopes()` and `can_upload_to_inbox()`, make `missing_scopes()` accept the scope set to check, and let `TikTokScopeMissing` keep any name in `KNOWN_SCOPES`
- [X] T007 [US3] In backend/app/tiktok_connections.py: `_complete_with_credential` requires `has_requested_scopes()` (failing before `complete_connection`); `_renew` keeps base-only rules; `_permissions` lists `KNOWN_SCOPES` granted; messages say "grant every requested permission"
- [X] T008 [US3] Add `capabilities: TikTokCapabilitiesRead {direct_post, inbox_upload}` to `TikTokPermissionsRead` in backend/app/schemas.py and fill it in backend/app/tiktok_connections.py; mirror the type in frontend/src/types.ts
- [X] T009 [P] [US3] Show "Upload to Inbox: available / needs Reconnect (video.upload)" from `capabilities` in frontend/src/components/TikTokConnectionPanel.tsx with a test in frontend/src/components/TikTokConnectionPanel.test.tsx

### Checkpoint

- [X] T010 [US3] ⛔ **V1a (manual, usuario)**: run targeted tests (`uv run pytest tests/test_tiktok_scopes.py tests/test_tiktok_connect.py tests/test_tiktok_tokens.py`), then quickstart.md V1a with real TikTok; record PASS/STOP in specs/014-tiktok-inbox-upload/quickstart.md "Resultados". **STOP here** until the user confirms PASS

---

## Phase 3: Foundational (blocking prerequisites)

**Purpose**: migración, estado genérico neutral, modo y extracción de la transferencia común.

### Tests (write first)

- [X] T011 [P] Extend backend/tests/test_migrations.py for `0013`: upgrade with pre-existing TikTok publications (with and without options rows, any status) → every one has options with `mode = 'DIRECT_POST'`; existing `tiktok_publish_runs` → `mode = 'DIRECT_POST'`; new options rows get `mode` NULL (no server default); `publications.status = 'awaiting_user_action'` accepted with `published_at` NULL and rejected with `published_at` set; run CHECKs (`delivered` only for Upload to Inbox); downgrade with zero `awaiting_user_action` publications restores the 0012 schema; downgrade with at least one `awaiting_user_action` publication **fails explicitly** with a clear message and leaves the database (schema and rows) unchanged — no row is ever mapped to another status
- [X] T012 [P] Write backend/tests/test_awaiting_user_action.py (core only, `FakePublisher`, no TikTok): outcome with `awaiting_user_action=True` → attempt `succeeded`/`done`, publication `awaiting_user_action`, `published_at` NULL; publish/patch/cancel/tiktok-free edits → 409; `publish-check` not eligible; duplicate publication of same content+account rejected; scheduler cycle and `recover_interrupted_attempts` ignore it; queue ordering places it between `publishing` and `failed`
- [X] T013 [P] Write backend/tests/test_tiktok_mode.py baseline (before T020 implements it): `PUT/GET tiktok-options` accept and return `mode` (`null`, `DIRECT_POST`, `INBOX_UPLOAD`); a new TikTok publication without options or with `mode = null` reports `tiktok_mode_required` (field `mode`) in `tiktok-options`, `publish-check` and arming; mode not editable in `publishing` / `awaiting_user_action` / `published` (409 `publication_not_editable`); publications migrated with `mode = 'DIRECT_POST'` keep their Direct Post readiness (same problems as in Feature 013, no `tiktok_mode_required`)

### Implementation

- [X] T014 Add `PublicationStatus.AWAITING_USER_ACTION`, updated CHECKs, `TikTokMode` enum, `TikTokPublicationOptions.mode`, `TikTokPublishPhase.DELIVERED` and new `TikTokPublishRun` columns/CHECKs (data-model.md) in backend/app/models.py
- [X] T015 Create backend/migrations/versions/0013_tiktok_inbox_upload.py: batch-recreate `publications` CHECKs (pattern of 0005); add `tiktok_publication_options.mode` without default, set existing rows to `DIRECT_POST`, insert default options rows with `DIRECT_POST` for TikTok publications without one; batch-recreate `tiktok_publish_runs` with `mode` (existing → `DIRECT_POST`), `delivered_to_inbox_at`, `user_published_at`, `public_post_count` and new CHECKs; downgrade first counts `awaiting_user_action` publications and, if any exist, raises an explicit error ("Cannot downgrade: N publication(s) are awaiting user action in TikTok; resolve them first.") before changing anything; otherwise restores 0012
- [X] T016 In backend/app/publishing.py add `PublishOutcome.awaiting_user_action: bool = False` and handle it in `persist_success` (publication `AWAITING_USER_ACTION`, `published_at` NULL, no external id/url); add `Publisher.follow_up(...)` to the protocol plus `UserActionCompleted` / `UserActionFailed` types (no endpoint yet)
- [X] T017 In backend/app/publications.py handle the new status: `ensure_editable` and `cancel_publication` reject it with `publication_not_editable`, queue `status_rank` and sort key, not in `HISTORY_STATUSES`; add `follow_up` returning `None` in backend/app/youtube_publishing.py, backend/app/instagram_publishing.py, backend/app/threads_publishing.py; run affected regressions (`uv run pytest tests/test_publications*.py tests/test_publish*.py tests/test_scheduler*.py`)
- [X] T018 [P] Add `"awaiting_user_action"` to `PublicationStatus`, `PUBLICATION_STATUS_LABELS` ("Awaiting your action") and a `publicationStatusLabel(publication)` helper returning "Ready in TikTok" for TikTok in frontend/src/types.ts and frontend/src/utils.ts, with cases in frontend/src/utils.test.ts; make frontend/src/components/PublicationQueue.tsx group it as its own status
- [X] T019 Extract the FILE_UPLOAD transfer (run creation, `publish_id` commit, intermediate chunks with retries and `416` policy, digest check, write-ahead, single last chunk, bounded polling loop) from backend/app/tiktok_publishing.py into `FileUploadTransfer` in new backend/app/tiktok_transfer.py, parameterized by an `init` callable and a status `interpret` callable (research §4); Direct Post keeps its exact behaviour
- [X] T020 Add `mode` to `TikTokPublicationOptionsWrite`/`Read` (+ `modes` availability) in backend/app/schemas.py and to `get/save_tiktok_options` in backend/app/tiktok_publishing.py; Direct Post `check`/`arming_problems` add `tiktok_mode_required` when `mode` is NULL; update options fixtures in existing TikTok tests to send `mode: "DIRECT_POST"`
- [X] T021 Run the existing Direct Post suites as equivalence proof: `uv run pytest tests/test_tiktok_publish.py tests/test_tiktok_anti_duplicates.py tests/test_tiktok_upload_errors.py tests/test_tiktok_recovery.py tests/test_tiktok_reconcile.py tests/test_tiktok_publish_secrets.py tests/test_tiktok_options.py tests/test_tiktok_scheduler.py`, plus T011/T012/T013. These suites keep **all their expectations and behaviour**; only fixtures/setup may change to include the new `mode` field (T020). Fix only the extraction, never an expectation
- [X] T022 [P] Extend architecture tests in backend/tests/test_publications_states.py: core modules still free of TikTok names; `tiktok_transfer.py` and `tiktok_inbox.py` do not import `media_delivery`, Instagram or Threads

**Checkpoint**: foundation lista; Direct Post idéntico; el núcleo conoce el nuevo estado.

---

## Phase 4: User Story 2 — Elegir el modo y enviar ahora a TikTok (Priority: P1) 🎯 MVP

**Goal**: modo obligatorio por publicación; `Send to TikTok` sube el vídeo al inbox y deja la
publicación en Ready in TikTok.

**Independent Test**: publicación de vídeo pequeño, `mode = INBOX_UPLOAD`, conexión con tres
scopes; `POST /publish` → un `inbox_init` sin `post_info`, `publish_id` antes del primer byte,
write-ahead, `SEND_TO_USER_INBOX` → intento `succeeded`, publicación `awaiting_user_action`,
run `delivered`, sin más lecturas de estado; ningún secreto expuesto.

### Tests (write first)

- [X] T023 [P] [US2] Extend backend/tests/test_tiktok_mode.py with Upload to Inbox cases (mode baseline already covered by T013): `INBOX_UPLOAD` without `video.upload` capability → `tiktok_upload_permission_missing` (field `mode`, connection not marked reconnect); `INBOX_UPLOAD` needs no privacy, AIGC, caption nor consent; `POST tiktok-consent` in `INBOX_UPLOAD` → 409 `tiktok_consent_not_applicable`
- [X] T024 [P] [US2] Write backend/tests/test_tiktok_inbox_publish.py: single-chunk Inbox publish (init once, body has only `source_info`, `submitted` without `post_info`), `publish_id` committed before first `PUT`, write-ahead before last chunk, polling stops at `SEND_TO_USER_INBOX` (no further status reads), run `delivered` with `delivered_to_inbox_at`, attempt `succeeded` with `external_id`/`external_url` NULL and `details.tiktok_mode`; early `PUBLISH_COMPLETE` → `published`; `FAILED` → determined failure; unknown/`PROCESSING_DOWNLOAD` → ambiguous; status stays `PROCESSING_UPLOAD` until the processing window expires → attempt failed with `outcome_determined = false` (reconcilable with the same `publish_id`), never a success, publication never `awaiting_user_action`/`published`, and no second `inbox_init`; `publicaly_available_post_id` only counted in `public_post_count`
- [X] T025 [P] [US2] Write backend/tests/test_tiktok_inbox_secrets.py: after an Inbox publish, DB dump, captured logs, every API response (`/attempts`, `/tiktok-options`, `/publications/{id}`) and error messages contain no upload URL (or host+query), tokens, `Authorization` nor `publish_id`

### Implementation

- [X] T026 [US2] Add `INBOX_VIDEO_INIT_ENDPOINT` and `init_inbox_video(access_token, source_info) -> InitResult` (same validation as `init_video_post`) in backend/app/tiktok_gateway.py
- [X] T027 [US2] Create backend/app/tiktok_inbox.py with the Inbox status interpreter (`SEND_TO_USER_INBOX` → `PublishOutcome(awaiting_user_action=True, details={"tiktok_mode": "INBOX_UPLOAD", "delivered_to_inbox": True})` and run `delivered`; `PUBLISH_COMPLETE` → published outcome with run `user_published_at`; `FAILED` → `map_fail_reason` with Inbox wording; else unresolved), Inbox messages and `inbox_check_problems` (capability + video rules without `max_video_post_duration_sec`)
- [X] T028 [US2] In backend/app/tiktok_publishing.py dispatch by mode: `check` (mode required; Inbox → `inbox_check_problems`), `prepare` (Inbox: no Creator Info, SHA-256 digest == checksum, payload with `mode`, `source_info`, `submitted = {mode, source_info, video}`), `upload` (create run with `mode`, `FileUploadTransfer` with `init_inbox_video` + Inbox interpreter); Direct Post path unchanged
- [X] T029 [US2] Add `TikTokMode` and `mode`/`modes` to TikTok option types and API calls in frontend/src/types.ts and frontend/src/api.ts; extend frontend/src/test-fake-api.ts
- [X] T030 [US2] In frontend/src/components/TikTokPublishOptions.tsx add the required mode radio ("Direct Post" / "Upload to Inbox", none selected when `mode` is null, disabled option with its reason); in Inbox hide Creator Info, privacy, interactions, disclosure, AIGC, caption and declaration and show the "finish the post in TikTok" notice (research §12); tests in frontend/src/components/TikTokPublishOptions.test.tsx (in `INBOX_UPLOAD`, no caption, privacy or hashtag value is rendered as the post's configuration)
- [X] T031 [US2] In frontend/src/components/PublicationDetail.tsx label the publish button **Send to TikTok** for Inbox and block Publish/Schedule without mode (showing "Choose how to send this video to TikTok"); in frontend/src/components/PublishNowDialog.tsx add the Inbox variant without the Direct Post declaration ("AutoPublisher will upload this video to TikTok. You'll get a TikTok inbox notification to review, edit and publish it."); tests in frontend/src/components/PublicationDetail.test.tsx
- [X] T032 [US2] Show **Ready in TikTok** with "Open your TikTok inbox to review, edit and publish the video." and "TikTok inbox notification (not necessarily a phone push notification)" for `awaiting_user_action` TikTok publications in frontend/src/components/PublicationDetail.tsx (minimal version; full delivery panel in T047)

**Checkpoint**: envío manual Inbox funcional con fakes.

---

## Phase 5: User Story 1 — Checkpoint V1 real (Priority: P1)

**Goal**: responder con TikTok real si Upload to Inbox funciona con la cuenta pública y el
cliente Sandbox/no auditado.

**Independent Test**: quickstart.md V1b.

- [X] T033 [US1] Run the targeted suites of Phases 3–4 (`uv run pytest tests/test_tiktok_mode.py tests/test_tiktok_inbox_publish.py tests/test_tiktok_inbox_secrets.py tests/test_awaiting_user_action.py tests/test_migrations.py`, `npm test -- TikTok`), `uv run ruff check .`, `uv run mypy .`, `npm run typecheck`
- [X] T034 [US1] Apply migration 0013 to the local database (`uv run alembic upgrade head`) and verify existing TikTok publications read `mode = DIRECT_POST`
- [X] T035 [US1] Prepare `/tmp/tt-inbox/inbox-small.mp4` per quickstart.md and import it into a test project (user)
- [X] T036 [US1] Execute quickstart.md V1b steps 1–6 (mode selector, Inbox view, Send to TikTok, init, upload, `SEND_TO_USER_INBOX`) and record values (time to inbox, statuses) (user + agent reading DB/logs)
- [X] T037 [US1] Execute quickstart.md V1b steps 7–9 on the phone: notification visible, opens TikTok editor with the video, editable; do **not** publish (user)
- [X] T038 [US1] Execute quickstart.md V1b step 11 security grep of logs and SQLite (agent)
- [X] T039 [US1] ⛔ **V1b**: record the explicit answer "Does Upload to Inbox work with our public account and Sandbox/unaudited client?" and PASS/STOP for each V1b sub-step (1–11) in the existing quickstart.md "Resultados" table, without sensitive data; update research.md §0/§13 with observed facts. **STOP here**; continue with T040 only on PASS

---

## Phase 6: User Story 5 — Check status (Priority: P2)

**Goal**: desde Ready in TikTok, una consulta del mismo `publish_id` lleva a `published` /
`failed` o mantiene el estado, sin tocar el intento de entrega.

**Independent Test**: publicación `awaiting_user_action` con run `delivered`; fake devuelve cada
estado; comprobar transiciones, intento intacto, una lectura por llamada, sin intentos nuevos.

### Tests (write first)

- [X] T040 [P] [US5] Write backend/tests/test_publish_follow_up.py (core, `FakePublisher`): `follow_up_publication` only from `awaiting_user_action` (else 409 `publication_not_awaiting`); completed → `published` with `published_at`; failed → `failed`; None → unchanged; exception → unchanged and propagated; conditional update is idempotent under concurrent calls; the attempt row is byte-identical before/after; attempt count unchanged
- [X] T041 [P] [US5] Write backend/tests/test_tiktok_inbox_check_status.py: `POST /check-status` → `awaiting` (run `last_status_at` updated), `published` (run `succeeded`, `user_published_at`), `failed` (run `failed`, safe `fail_reason`, `after_delivery_failure` in `tiktok-delivery`); 5xx/network → 503 `tiktok_unavailable`; 429 → 503 `tiktok_rate_limited`; `invalid_publish_id`/`token_not_authorized_for_specified_publish_id` → 409 `tiktok_status_unavailable`; disconnected → 409; exactly one status request per call; never `inbox_init`; `GET /tiktok-delivery` for each derived state

### Implementation

- [X] T042 [US5] In backend/app/publishing.py implement `follow_up_publication(session, publication_id, ctx, publishers)` with conditional `UPDATE ... WHERE status = 'awaiting_user_action'` and the neutral route `POST /api/publications/{id}/check-status` returning `CheckStatusRead` (add schema in backend/app/schemas.py)
- [X] T043 [US5] Implement `TikTokPublisher.follow_up` delegating to backend/app/tiktok_inbox.py: requires run `INBOX_UPLOAD` + `delivered` + `publish_id`; one `call_with_token` status read; maps statuses per research §6/§8; updates the run only (never the attempt)
- [X] T044 [US5] Add `GET /api/publications/{id}/tiktok-delivery` (`TikTokDeliveryRead`, no network) in backend/app/tiktok_inbox.py and register its router in backend/app/main.py
- [X] T045 [P] [US5] Add `checkPublicationStatus` and `getTikTokDelivery` to frontend/src/api.ts, types to frontend/src/types.ts and fakes to frontend/src/test-fake-api.ts
- [X] T046 [US5] Create frontend/src/components/TikTokInboxDelivery.tsx (states Scheduled / Uploading / Processing in TikTok / Ready in TikTok / Published / Failed, instruction text, **Check status** button only in Ready, disabled while pending, shows result message) with frontend/src/components/TikTokInboxDelivery.test.tsx asserting that in every Upload to Inbox state (incl. Ready in TikTok and Published) no caption, privacy, sound, effects, hashtags, cover nor other final post metadata is presented as known configuration
- [X] T047 [US5] Mount `TikTokInboxDelivery` in frontend/src/components/PublicationDetail.tsx (replacing the minimal T032 block) and, in frontend/src/components/PublicationAttempts.tsx, show "Delivered to TikTok inbox" for the attempt separately from the final publication state ("Published in TikTok" / "Failed in TikTok"); tests in frontend/src/components/PublicationAttempts.test.tsx

---

## Phase 7: User Story 6 — Nunca reenviar ante esperas, cortes o reinicios (Priority: P2)

**Goal**: anti-duplicados y recuperación Inbox.

**Independent Test**: interrupción en cada fase y reinicio; init Inbox ≤ 1 por intento; Ready in
TikTok persiste sin consultas; ambiguo reconciliable solo con su `publish_id`.

- [X] T048 [P] [US6] Write backend/tests/test_tiktok_inbox_recovery.py: interruption before init / after `publish_id` / mid-chunks → determined failure, no resume; after write-ahead → ambiguous; restart with `awaiting_user_action` → unchanged and zero TikTok requests; reconcile of an ambiguous Inbox attempt: `SEND_TO_USER_INBOX` → attempt `succeeded` + publication `awaiting_user_action`, `PUBLISH_COMPLETE` → `published`, `FAILED` → determined failure, other → still uncertain; ambiguous attempt requires `confirm_remote_checked` before a new attempt; `inbox_init` never called by recovery/reconcile
- [X] T049 [US6] Make `Reconciliation.published_at` optional and route `persist_reconciled_success` to `AWAITING_USER_ACTION` when `outcome.awaiting_user_action` in backend/app/publishing.py, with a core case in backend/tests/test_publish_reconcile.py
- [X] T050 [US6] Extend `TikTokPublisher.reconcile` in backend/app/tiktok_publishing.py to use the run `mode`: Inbox statuses via backend/app/tiktok_inbox.py (`SEND_TO_USER_INBOX` → `Reconciliation(published_at=None, outcome awaiting)`, run `delivered`); Direct Post unchanged

---

## Phase 8: User Story 7 — Fallos comprensibles y envíos pendientes (Priority: P3)

**Goal**: taxonomía Inbox (research §9).

**Independent Test**: cada señal produce su código, determinación, sin reintento indebido y sin
`Reconnect required` por `video.upload`.

- [X] T051 [P] [US7] Write backend/tests/test_tiktok_inbox_errors.py: `spam_risk_too_many_pending_share` → `tiktok_too_many_pending_shares`, determined, no retry, one init only, message mentions pending uploads in TikTok; `scope_not_authorized` on Inbox init → `tiktok_upload_permission_missing`, connection stays `connected`; `spam_risk_user_banned_from_posting`, `invalid_param`, `access_token_invalid`, `rate_limit_exceeded`, 5xx on init → mapped as research §9; `FAILED` fail reasons (incl. `auth_removed` → reconnect as in 013) with Inbox wording; Direct Post `scope_not_authorized` behaviour unchanged
- [X] T052 [US7] Add `spam_risk_too_many_pending_share` to `POST_REJECTION_CODES` in backend/app/tiktok_gateway.py and the Inbox error mapping (init errors, fail reasons, "Nothing was sent to TikTok." wording) in backend/app/tiktok_inbox.py, wired into the transfer for Inbox runs

---

## Phase 9: User Story 8 — Vídeos grandes en varios chunks (Priority: P3)

**Goal**: multi-chunk Inbox con la transferencia compartida.

**Independent Test**: vídeo pequeño con `chunk_size` inyectado → varios chunks; `206`, `5xx`
reintentado en intermedios, `416` según política, `403` URL caducada, último chunk sin reenvío.

- [X] T053 [P] [US8] Write backend/tests/test_tiktok_inbox_upload_errors.py: multi-chunk Upload to Inbox transfer with injected chunk size (sequential `Content-Range`, progress by confirmed bytes), intermediate `5xx` retried on the same buffer, `416` accepted only per policy, `403` → `tiktok_upload_expired`, last chunk non-`201` → status only (never resent), deadline exceeded → determined failure
- [X] T054 [US8] Fix any Inbox-specific gap revealed by T053 in backend/app/tiktok_transfer.py or backend/app/tiktok_inbox.py (the transfer itself must stay mode-agnostic)

---

## Phase 10: User Story 4 — Programar el envío a TikTok (Priority: P2)

**Goal**: "Send to TikTok at 18:00" con el scheduler genérico.

**Independent Test**: armado con modo Inbox (sin consentimiento de Direct Post), ejecución
`scheduled` única, pausa, carreras, no re-ejecución desde `awaiting_user_action`.

- [X] T055 [P] [US4] Write backend/tests/test_tiktok_inbox_scheduler.py: arming requires mode (`tiktok_mode_required`) and, for Inbox, capability but no consent; due armed publication runs once with trigger `scheduled` and reaches `awaiting_user_action`; paused automation → not run, manual send still available; manual/scheduler race and two concurrent cycles → one execution; later cycles never touch `awaiting_user_action`; losing `video.upload` before the due time → determined preflight failure without network
- [X] T056 [US4] Update `TikTokPublisher.arming_problems` in backend/app/tiktok_publishing.py by mode (Inbox: mode + capability + local video checks; Direct Post unchanged)
- [X] T057 [US4] In frontend/src/components/PublicationDetail.tsx show for Inbox schedules "AutoPublisher starts sending at this time; the TikTok inbox notification may arrive later." and the `Scheduled` delivery state; test in frontend/src/components/PublicationDetail.test.tsx

---

## Phase 11: Polish & Cross-Cutting

- [X] T058 [P] Extend frontend/src/storage-safety.test.tsx with Inbox flows (no tokens, upload URL or `publish_id` in browser storage)
- [X] T059 [P] Re-run and extend backend/tests/test_tiktok_inbox_secrets.py with Check status, delivery and error responses
- [X] T060 [P] Update docs/tiktok-publishing.md: two modes, Upload to Inbox flow, Ready in TikTok vs Published, Check status, pending-share limit, no notification-time guarantee, stuck-awaiting limitation, V1b result about the public account
- [X] T061 [P] Update docs/tiktok-accounts.md: three requested scopes, base scopes vs `video.upload` capability, Reconnect behaviour (partial grant keeps the previous connection)
- [X] T062 [P] Update README.md: TikTok publishing section lists Direct Post and Upload to Inbox and the new `awaiting_user_action` status
- [X] T063 Add an explicit regression in backend/tests/test_awaiting_user_action.py: successful Direct Post, YouTube, Instagram and Threads publishes (each with its existing fake) end in `published` with `awaiting_user_action` false and never produce `awaiting_user_action`; then run Feature 013 / 012 regressions and the other platforms because the core changed: `uv run pytest tests/test_tiktok_*.py tests/test_youtube_*.py tests/test_instagram_*.py tests/test_threads_*.py tests/test_publish*.py tests/test_scheduler*.py`
- [X] T064 Prepare `/tmp/tt-inbox/inbox-multi.mp4` and run quickstart.md V2 steps 1–8 (scheduled send, pause/resume, restart, Check status before and after publishing manually in TikTok, multi-chunk) (user + agent)
- [X] T065 Run quickstart.md V2 step 9: Direct Post regression with the account temporarily private, then back to public (user)
- [X] T066 Run quickstart.md V2 steps 10–11 (security checks; manual deletion of test posts/drafts in TikTok) (user + agent)
- [X] T067 Record V2 PASS/STOP in specs/014-tiktok-inbox-upload/quickstart.md "Resultados" and update research.md with confirmed facts
- [X] T068 Full quality gates once: `cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .`; `cd frontend && npm test && npm run lint && npm run format:check && npm run typecheck && npm run build`; report any failure

---

## Dependencies & Execution Order

- **Phase 1** → **Phase 2 (US3, V1a)**: US3 no necesita la migración; se valida primero porque
  sin `video.upload` nada más tiene sentido.
- **Phase 3 (Foundational)** depende de Phase 1; bloquea todas las historias restantes.
- **Phase 4 (US2)** depende de Phase 3 y de US3.
- **Phase 5 (US1, V1b)** depende de US2 + US3. ⛔ Nada del Bloque 2 antes de V1b PASS.
- **Phases 6–10** (US5, US6, US7, US8, US4) dependen de V1b PASS; entre sí: US6 (T049) antes de
  US4 si se prueban reinicios programados; US5 antes de T057 (estado `Scheduled` del panel usa
  `tiktok-delivery`). Por lo demás, independientes.
- **Phase 11** al final; T063 antes de V2; T068 una sola vez tras V2.

### Story completion order

US3 → (Foundation) → US2 → US1 (V1b) → US5 → US6 → US7 → US8 → US4 → Polish

## Parallel Execution Examples

- Phase 1: T001 ∥ T002.
- US3: T003 ∥ T004 (tests); T009 en paralelo con T005–T008 una vez fijado el tipo `capabilities`.
- Foundational: T011 ∥ T012 ∥ T013 ∥ T022 (tests; T013 antes de T020); T018 (frontend) ∥ T014–T017 (backend).
- US2: T023 ∥ T024 ∥ T025; T029 ∥ T026.
- US5: T040 ∥ T041; T045 ∥ T042–T044.
- Bloque 2: T048 (US6), T051 (US7), T053 (US8), T055 (US4) son archivos de test distintos y
  pueden escribirse en paralelo.
- Polish: T058 ∥ T059 ∥ T060 ∥ T061 ∥ T062.

## Implementation Strategy

1. **MVP real temprano**: Phase 1 → US3 → **V1a** → Foundation → US2 → **V1b**. Con esto se
   responde a la pregunta clave con TikTok real antes de invertir en scheduler, Check status o
   recuperación.
2. **Incremental**: tras V1b PASS, US5 (Check status) da el ciclo completo manual; US6/US7/US8
   endurecen; US4 añade la programación.
3. **Cierre**: regresiones amplias (T063), V2 real, quality gates completos una vez (T068).
4. Commits pequeños por tarea o grupo coherente, en inglés, solo cuando el usuario lo pida.
