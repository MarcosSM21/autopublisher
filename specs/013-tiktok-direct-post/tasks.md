---

description: "Task list for real TikTok video publishing with Direct Post and FILE_UPLOAD (Feature 013)"
---

# Tasks: Publicación real de vídeo en TikTok mediante Direct Post (FILE_UPLOAD)

**Input**: Design documents from `specs/013-tiktok-direct-post/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige (FR-062, SC-012). Ningún test usa Internet, TikTok real ni el
keyring real: `FakeTikTok` (ampliado), `InMemoryCredentialStore`, `FakeClock`, `sleep`
instantáneo, `probe_video_streams` simulado y archivos de prueba pequeños; los tamaños grandes
se prueban con el planificador puro y constantes de chunk inyectables (nunca archivos de GB).
En cada fase funcional los tests se escriben **primero** y deben fallar antes de implementar.
Durante el desarrollo: tests dirigidos (`uv run pytest tests/test_tiktok_….py`, `npm test --
TikTok`); suite completa solo en T046 (antes de V1), T073 (antes de V2) y en CI.

**Organization**: fases según plan.md (Bloque 1 → V1 → Bloque 2 → V2), con etiquetas de historia
de usuario de la spec (US1–US8). Código, comentarios, mensajes de API/UI, README, docs y commits
en inglés.

> ## ⛔ Límite de `/speckit-implement`
>
> **Implementar hasta la tarea V1 (T047) inclusive y DETENERSE.** T047 es una validación manual
> con TikTok real que ejecuta el usuario. Solo con V1 en **PASS** (registrado en
> `quickstart.md → Resultados`) se continúa con T048 en adelante. Si V1 da **STOP**, revisar
> spec/plan antes de tocar nada más.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivo distinto, sin dependencias pendientes).
- **[Story]**: US1 Publish now · US2 revisión/opciones/Creator Info · US3 caption · US4 preflight
  · US5 scheduler · US6 anti-duplicados · US7 multi-chunk · US8 errores y conexión.

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/` (comandos desde
  `backend/` con `uv run …`).
- Frontend: `frontend/src/`, `frontend/src/components/` (comandos desde `frontend/`).

## Reglas transversales (aplican a todas las tareas)

- **Alcance**: solo VIDEO, Direct Post, `source = FILE_UPLOAD`, `video.publish`. Prohibido:
  fotos, `PULL_FROM_URL`, `MediaDeliveryProvider`/R2, `video.upload`, `video.list`, listar posts,
  App Audit, transcoding, portada, cross-posting.
- **Endpoints** (research §2): `POST https://open.tiktokapis.com/v2/post/publish/creator_info/query/`,
  `POST /v2/post/publish/video/init/`, `PUT {upload_url}` (sin `Authorization`),
  `POST /v2/post/publish/status/fetch/`. Host desde `TIKTOK_API_HOST` existente.
- **Credenciales**: solo `get_valid_credentials` / `call_with_token` / `mark_scope_not_authorized`
  / `mark_reconnect_required` de `tiktok_connections.py`. `call_with_token` solo para Creator Info
  y estado; `init` nunca se repite.
- **Anti-duplicados** (research §11–§14): `init` ≤ 1 por intento; `publish_id` commit antes del
  primer byte; write-ahead = `reporter.enter_final_chunk()` + run `final_chunk` antes del último
  `PUT`; último chunk **exactamente un intento**, nunca reenviado y nunca un segundo Direct Post.
  Una vez alcanzado el write-ahead, `reporter.enter_finalizing()` ocurre tras **cualquier**
  resultado del último `PUT`: `201` → polling normal; cualquier otro resultado (red, timeout,
  `4xx`, `5xx`, inesperado) → solo estado del mismo `publish_id` (`PUBLISH_COMPLETE` éxito,
  `FAILED` determinado, `PROCESSING_UPLOAD`/error/inesperado ambiguo);
  nunca `leave_final_chunk()` ni `enter_processing()`; nunca un
  segundo `publish_id`; reconciliación solo con el `publish_id` original.
- **Digest** (research §6): `prepare` = SHA-256 en streaming == `Content.checksum`; `upload` =
  SHA-256 incremental sobre los mismos buffers subidos; último chunk leído en memoria e incorporado
  **antes** del write-ahead; si no coincide → determinado, sin write-ahead ni `PUT` final.
- **Secretos**: `upload_url` solo en `UploadUrl` (sin repr) dentro de `upload()`; nunca en DB,
  `submitted`, `details`, errores, logs, API, navegador. `publish_id` no se expone por la API.
- **Chunks** (research §9): `SINGLE_CHUNK_MAX = 64_000_000`, `CHUNK_SIZE = 33_554_432`,
  `floor`, ≤ 119 chunks para 4 000 000 000 B.
- **Polling** (research §15): 3 s, luego (3,5,5,10,10,15,15) s y cada 30 s, máx. 10 min; 429
  duplica la siguiente espera (≤ 60 s); rodajas de 1 s con `should_stop()`.

---

## Phase 0: Precondiciones (estado existente, sin código)

- [X] T001 Verify the preconditions without changing code and record them as a "Precondiciones" note (PASS/STOP, no secrets) at the end of `specs/013-tiktok-direct-post/quickstart.md`: Feature 012 merged on `main`; the TikTok `Account` is `Connected` and `Verify` succeeds; the connection's scopes include `video.publish`; the Sandbox config in `backend/data/tiktok-app.json` is the one from Feature 012; the target TikTok account is set to private; `ffprobe -version` works. No OAuth work is repeated; if any precondition fails, STOP and fix it with Feature 012's flows

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T002 Write migration tests first in `backend/tests/test_migrations.py`: `0012_tiktok_publishing` upgrade/downgrade, both tables and columns of data-model.md, each CHECK constraint (`privacy_valid`, `brand_toggles_need_disclosure`, `branded_not_private`, `consent_complete`, run `phase_valid`, `confirmed_bytes` range, `total_chunk_count` range, write-ahead needs `publish_id`), `publish_id` UNIQUE and the `publication_id` index
- [X] T003 Add `TikTokPublicationOptions`, `TikTokPublishPhase` and `TikTokPublishRun` to `backend/app/models.py` and create `backend/migrations/versions/0012_tiktok_publishing.py` exactly as in data-model.md (FK `RESTRICT`, no back-relationship from `Publication`, no column for `upload_url`)
- [X] T004 [P] Extend `FakeTikTok` in `backend/tests/fakes.py` with endpoints `creator_info`, `init`, `upload` (fake host `https://open-upload.tiktokapis.example/upload/?upload_id=…&upload_token=SECRET…`) and `status`: programmable Creator Info payloads/codes, init payloads/codes, per-chunk upload responses (206/201/400/403/404/416 with or without `Content-Range`/5xx/429/transport error/timeout/lost response), status sequences, a request log with method/path/headers/body sizes, a hook to run assertions inside a request (e.g. read the DB during a `PUT`), and rejection (test failure) of any unknown path such as video list endpoints
- [X] T005 [P] Add TikTok publishing fixtures to `backend/tests/conftest.py`: connected TikTok account (reusing Feature 012 fixtures), small MP4/MOV/WebM video `Content` files with real SHA-256 checksums, a fake `probe_video_streams` factory, a TikTok publication, a helper that writes complete options + valid consent, and `TikTokPublishSettings` with instant `sleep`, `FakeClock` and injectable `single_chunk_max`/`chunk_size` for multi-chunk tests with KB-sized files

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: reglas puras, gateway, DTOs, taxonomía, redacción y arquitectura. Bloquea todas las
fases siguientes.

### Tests (escribir primero)

- [X] T006 [P] Write caption tests in `backend/tests/test_tiktok_caption.py` with the shared case list of research §7 (ASCII `"a"*2199/2200/2201`, BMP `"é"`/`"中"` = 1, `"😀"` = 2, `"𝐀"` = 2, `"👨‍👩‍👧"` = 8, `"🇪🇸"` = 4, `"❤️"` = 2, 1100×`"😀"` = 2200 valid and +`"a"` invalid, empty): composition description/hashtags/both/neither via `description_with_hashtags`, title never included, no trimming/normalisation, `> 2200` produces `tiktok_caption_invalid` without truncation, and a guard that the count is not `len()`
- [X] T007 [P] Write chunk planner tests in `backend/tests/test_tiktok_chunks.py` (pure, no files): the exact table of research §9 (1 MiB, 5 MiB, 20 MiB, 64 000 000, 64 000 001, 64 MiB, 65 MiB, 128 MiB, 500 MiB, 4 000 000 000) for `chunk_size`, `total_chunk_count` and last-chunk size; per-chunk byte ranges and the `Content-Range` string `bytes first-last/total`; property checks over many sizes up to 4 000 000 000 (single chunk ≤ 64 000 000; multi-chunk `chunk_size` in [5 MiB, 64 000 000], `count == size // chunk_size`, 2 ≤ count ≤ 1000, last chunk in [chunk_size, 2·chunk_size) and < 128 000 000, ranges contiguous and covering the file); size ≤ 0 rejected
- [X] T008 [P] Write video rule tests in `backend/tests/test_tiktok_video_rules.py` for the matrix of research §8: container mp4/mov/webm vs others, image `Content` rejected, missing file, size mismatch with `Content.size_bytes`, size 4 000 000 000 vs +1, ffprobe unavailable/unreadable → `tiktok_video_uninspectable`, no video stream, codecs h264/hevc/vp8/vp9 vs others, width/height 359/360/4096/4097, duration 0/600/601 and vs a creator max, FPS with the exact rule `22.99 <= fps <= 60.01` (22.98 reject, 22.99 accept, 23.0 accept, 23.976 accept, 59.94 accept, 60.0 accept, 60.01 accept, 60.02 reject) and missing FPS → `delegated_checks == ["frame_rate"]`, MIME per container, and the original file bytes unchanged after the checks
- [X] T009 [P] Write option rule tests in `backend/tests/test_tiktok_option_rules.py`: commercial mapping OFF→false/false, Your brand→false/true, Branded→true/false, Both→true/true always present in `post_info`; disclosure ON with no toggle → `tiktok_disclosure_incomplete`; Branded + `SELF_ONLY` invalid; privacy NULL → `tiktok_privacy_required`; privacy ≠ `SELF_ONLY` with the unaudited client → `tiktok_privacy_not_allowed`; `is_aigc` NULL → `tiktok_aigc_required` and true/false accepted and sent explicitly; `disable_comment/duet/stitch == not allow_*` for all 8 combinations; interactions default false and never required; `title` omitted when the caption is empty; declaration version/text/links per toggle combination; labels "Promotional content"/"Paid partnership"
- [X] T010 [P] Write fingerprint and digest tests in `backend/tests/test_tiktok_fingerprint.py`: same inputs → same fingerprint; each of `open_id`, `Content.checksum`, caption, privacy, each `allow_*`, disclosure, each toggle, `is_aigc` and declaration version changes it; scheduled date and generic title do not; no fingerprint while options are incomplete; streaming file SHA-256 equals `hashlib.sha256(file bytes)` using bounded reads (spy: no read larger than 1 MiB); the incremental hasher fed with arbitrary buffer splits equals the full digest
- [X] T011 [P] Write gateway tests in `backend/tests/test_tiktok_gateway_post.py` against `FakeTikTok`: Creator Info strict DTO (valid; missing/empty nickname, non-bool flags, bool or ≤ 0 max duration, empty/non-list options → `TikTokUnexpectedResponse`; avatar/username optional; HTTP 200 `spam_risk_too_many_posts`/`spam_risk_user_banned_from_posting`/`reached_active_user_cap` → `TikTokPostRejected`); init JSON body shape and parsing of `publish_id`/`upload_url`, `UploadUrl` repr/str redacted, every documented init error code, unknown code → unexpected, 429 → `TikTokUnavailable(rate_limited=True)`, 5xx/transport → unavailable; `upload_chunk` headers (`Content-Type`, `Content-Length`, `Content-Range`, **no** `Authorization`), 206/201 with optional `Content-Range` parsing, 400/403/404 → `TikTokUploadRejected`, 416 → `TikTokUploadRangeMismatch(progress)` (response `Content-Range` = `bytes 0-{accepted_bytes}/{total}`, research §12), 5xx/transport/timeout → unavailable; status DTO (`publicaly_available_post_id` list, non-int items ignored, `fail_reason` sanitised to `^[a-z_]{1,64}$` or `unknown`, `uploaded_bytes`), `invalid_publish_id`/`token_not_authorized_for_specified_publish_id`; no exception message or `repr` contains a URL, token or response body
- [X] T012 [P] Write the error taxonomy table test in `backend/tests/test_tiktok_errors.py`: for every row of research §19 (TikTok code/HTTP/phase, before or after write-ahead) assert the AutoPublisher code, safe English message, determined flag, retry policy and connection effect (`R` or none)
- [X] T013 [P] Write log redaction tests in `backend/tests/test_tiktok_publish_secrets.py`: `RedactTikTokSecrets` replaces whole upload URLs (fake host above, `open-upload.tiktokapis.com/upload/?…`, query with `upload_token`/`upload_id`/`signature`) in `httpx`/`httpcore` log records, keeps existing redactions, and `str(UploadUrl(...))` never reveals the value
- [X] T014 [P] Add architecture tests in `backend/tests/test_publications_states.py`: `publishing`, `publications`, `scheduler`, `automation` and the Accounts core never import `tiktok_*`; `tiktok_media` and `tiktok_publishing` never import `media_delivery`, `media_delivery_s3`, `instagram_*` or `threads_*`; `tiktok_media` imports no HTTP client

### Implementation

- [X] T015 Implement caption composition and `tiktok_caption_length` (UTF-16 code units: `len(s.encode("utf-16-le")) // 2`) with `TIKTOK_CAPTION_MAX = 2200` and caption problems in new `backend/app/tiktok_media.py` (makes T006 pass)
- [X] T016 Implement `ChunkPlan`/`plan_chunks(video_size, single_chunk_max, chunk_size)` with the default constants and per-chunk ranges in `backend/app/tiktok_media.py` (makes T007 pass)
- [X] T017 Implement the video validation matrix (`VideoCheck` with problems, summary values and `delegated_checks`, MIME per container) reusing `media.probe_video_streams`/`MIME_TYPES` in `backend/app/tiktok_media.py` (makes T008 pass)
- [X] T018 Implement option rules, `post_info`/`source_info` builders (interaction inversion, both commercial toggles always materialised, `is_aigc` explicit, no cover), declarations (`music-usage-2026-10-14`, `branded-music-usage-2026-10-14`, text, official links) and labels in `backend/app/tiktok_media.py` (makes T009 pass)
- [X] T019 Implement `consent_fingerprint(...)` (canonical JSON of research §6), `file_sha256(path)` with 1 MiB streaming reads and an incremental `UploadDigest` helper in `backend/app/tiktok_media.py` (makes T010 pass)
- [X] T020 Extend `backend/app/tiktok_gateway.py` with `CreatorInfo`, `InitResult`, `UploadUrl`, `ChunkResult`, `PublishStatus`, exceptions `TikTokPostRejected`, `TikTokUploadRejected`, `TikTokUploadRangeMismatch`, `rate_limited` on `TikTokUnavailable`, the extended `_classify`, and methods `query_creator_info`, `init_video_post`, `upload_chunk` (per-request timeout connect 10 s / write 300 s / read 120 s) and `fetch_publish_status`; every httpx error re-raised `from None` (makes T011 pass)
- [X] T021 Create `backend/app/tiktok_publishing.py` with constants (`CLIENT_AUDITED = False`, `UNAUDITED_PRIVACY_LEVEL = "SELF_ONLY"`), `TikTokPublishSettings` (sleep, clock, sleep slice, chunk constants, intermediate retry waits `(2, 5, 10)`, Creator Info retry wait 2 s, polling first wait/waits/interval/timeout, 429 cap, `upload_deadline` 50 min) and the error mapping helpers of research §19 (makes T012 pass)
- [X] T022 Extend `RedactTikTokSecrets` in `backend/app/tiktok_connections.py` to redact complete TikTok upload URLs and `upload_token`/`upload_id`/`signature` parameters, installed on the existing HTTP loggers (makes T013 pass)
- [X] T023 [P] Add `TikTokPublicationOptionsRead`/`Write`, `TikTokCreatorInfoRead`, `TikTokConsentWrite`, `TikTokDeclarationRead`, `TikTokVideoSummaryRead` and the consent state enum to `backend/app/schemas.py` as in contracts/api.md (no `publish_id`, no URL fields except the display-only avatar)

**Checkpoint**: `uv run pytest tests/test_tiktok_caption.py tests/test_tiktok_chunks.py tests/test_tiktok_video_rules.py tests/test_tiktok_option_rules.py tests/test_tiktok_fingerprint.py tests/test_tiktok_gateway_post.py tests/test_tiktok_errors.py tests/test_tiktok_publish_secrets.py tests/test_migrations.py tests/test_publications_states.py` en verde.

---

## Phase 3: Revisión, opciones, Creator Info y caption (US2 + US3, P1)

**Goal**: el usuario ve Creator Info real, el caption exacto con su contador y elige privacidad,
interacciones, AIGC y acepta la declaración; nada se preselecciona.

**Independent Test**: con `FakeTikTok`, abrir el panel de una publicación TikTok: Creator Info
consultado en cada apertura, privacidad sin valor, solo `SELF_ONLY` habilitado, interacciones
desmarcadas (deshabilitadas con motivo cuando Creator Info lo indica), AIGC sin decidir, caption y
conteo correctos, consentimiento guardado solo con la huella vigente.

### Tests (escribir primero)

- [X] T024 [P] [US2] Write `backend/tests/test_tiktok_options.py`: `GET` without a row returns the initial values (privacy null, interactions false, disclosure false/false, `is_aigc` null), `client_audited=false`, `allowed_privacy_levels=["SELF_ONLY"]`, caption/length/max, declaration, labels, `fingerprint=null`, problems, video summary; `PUT` full replacement; `422` for toggles without disclosure and `tiktok_branded_content_private`; `409 publication_not_editable` in `PUBLISHING`/`PUBLISHED`; `409 platform_not_supported` for other platforms; `409 tiktok_video_required` without video; no network request to `FakeTikTok`; no `publish_id`/URL in responses
- [X] T025 [P] [US2] Write `backend/tests/test_tiktok_consent.py`: `POST tiktok-consent` stores fingerprint/version/time when they match; `409 tiktok_consent_stale` on a different fingerprint or version; `409 tiktok_options_incomplete`; consent becomes `stale` after each material change (description override, hashtags override, `Content` description when not overridden, privacy, each interaction, disclosure, each toggle, AIGC, declaration version, linked `open_id` changed in `tiktok_connections`, a `Content` with another `checksum`) and stays `valid` after changing `scheduled_at` or the title; reconfirming over the current fingerprint makes it `valid` again; no network request
- [X] T026 [P] [US2] Write `backend/tests/test_tiktok_creator_info.py`: each `GET tiktok-creator-info` performs a new Creator Info request (two calls → two requests, no cache); response fields of contracts §3; `blocked` for the three cap/ban codes with `can_post=false`; `account_appears_public` when `PUBLIC_TO_EVERYONE` is offered; `video_within_max_duration`; token renewal on `access_token_invalid` through `call_with_token`; `scope_not_authorized` → reconnect required; errors `409 tiktok_not_connected`/`tiktok_reconnect_required`, `429 tiktok_rate_limited`, `503 tiktok_unavailable`, `502 tiktok_unexpected_response`; malformed payload → 502; nothing written to the DB
- [X] T027 [P] [US3] Write `backend/tests/test_tiktok_caption_preview.py`: the caption in `GET tiktok-options` follows publication overrides and `Content` metadata, never the title; editing description/hashtags with the generic `PATCH /api/publications/{id}` updates caption and count; a 2201-unit caption is reported with limit and real value and is never truncated; editing is rejected in `PUBLISHING`/`PUBLISHED`
- [X] T028 [P] [US3] Add the shared caption cases of T006 to `frontend/src/utils.test.ts` for `tiktokCaptionLength`

### Implementation

- [X] T029 [US2] Implement `GET`/`PUT /api/publications/{id}/tiktok-options` (options row helper, editability, structural validation, response assembly with caption, video summary, declaration, labels, fingerprint and consent state, local problems) in `backend/app/tiktok_publishing.py` (makes T024 and T027 pass)
- [X] T030 [US2] Implement `POST /api/publications/{id}/tiktok-consent` (server-side fingerprint recomputation with `Content.checksum` and the connection `open_id`, stale/incomplete errors) in `backend/app/tiktok_publishing.py` (makes T025 pass)
- [X] T031 [US2] Implement `GET /api/publications/{id}/tiktok-creator-info` with `call_with_token`, no persistence and the derived fields in `backend/app/tiktok_publishing.py`, and include the TikTok router in `backend/app/main.py` (makes T026 pass)
- [X] T032 [P] [US3] Implement `tiktokCaptionLength(s) = s.length` in `frontend/src/utils.ts` (makes T028 pass)
- [X] T033 [P] [US2] Add TikTok types to `frontend/src/types.ts`, `getTikTokOptions`, `saveTikTokOptions`, `getTikTokCreatorInfo`, `confirmTikTokConsent` to `frontend/src/api.ts`, and the same endpoints to `frontend/src/test-fake-api.ts`
- [X] T034 [US2] Write `frontend/src/components/TikTokPublishOptions.test.tsx` (minimal review): nickname and avatar from Creator Info; caption and counter (the video preview is added in T044); privacy select with no selected value and only `SELF_ONLY` enabled (others disabled with the unaudited reason); `Allow comments/duet/stitch` unchecked, the ones disabled by Creator Info greyed with reason; `AI-generated` Yes/No with none selected; declaration text with links and a confirmation checkbox that calls `confirmTikTokConsent` with the current fingerprint; disclosure shown OFF; `Refresh` refetches Creator Info; a blocked creator shows the message
- [X] T035 [US2] Implement the minimal `frontend/src/components/TikTokPublishOptions.tsx` and mount it in `frontend/src/components/PublicationDetail.tsx` (`"tiktok"` in `PUBLISHING_PLATFORMS`); consent wording "Consent recorded — matches saved publication metadata" plus the note "File integrity is rechecked before publishing." (never claiming the current bytes are verified) (makes T034 pass)

**Checkpoint**: tests de T024–T028 y T034 en verde.

---

## Phase 4: Publisher mínimo manual, un chunk (US1 + US4 + garantías US6, P1)

**Goal**: `Publish now` publica un vídeo pequeño (un chunk) con Direct Post real, con preflight
completo y todas las garantías anti-duplicados del punto irreversible.

**Independent Test**: con `FakeTikTok`, publicar un vídeo < 5 MB: Creator Info reconsultado,
un `init`, `publish_id` committed antes del `PUT`, write-ahead antes del único `PUT`, polling hasta
`PUBLISH_COMPLETE`, `PUBLISHED` sin post ID; cada fallo de preflight sin ninguna petición de
publicación.

### Tests (escribir primero)

- [X] T036 [P] [US4] Write `backend/tests/test_tiktok_preflight.py`: `check()` reports every local problem of contracts §5 with **zero** requests to `FakeTikTok`; `GET publish-check` never calls `init`; `prepare()` calls Creator Info exactly once and immediately before `init` (manual), never reusing the review result; stale privacy (selected level no longer offered), `SELF_ONLY` missing → `tiktok_privacy_unavailable`, interaction saved as allowed but now disabled → `tiktok_interaction_unavailable`, max duration lowered below the video → `tiktok_video_too_long`, cap/ban/active-user cap → `tiktok_creator_cannot_post`, malformed Creator Info → `tiktok_unexpected_response`, Creator Info 5xx retried once after 2 s, 429 not retried; file bytes changed on disk (checksum mismatch via streaming SHA-256) → `tiktok_video_changed`; in every failure the publication stays out of `PUBLISHING`, no attempt is created, `init` is never called and the message is local (never presented as a TikTok rejection); options are never modified
- [X] T037 [P] [US1] Write `backend/tests/test_tiktok_publish.py` (single chunk) and create `backend/tests/test_tiktok_reconcile.py` (minimal): after the normal app startup `app.state.publishers[Platform.TIKTOK]` is a `TikTokPublisher`; request order creator_info → init → PUT → status…; `post_info`/`source_info` exactly as research §5/§9 (`chunk_size == video_size`, count 1); `PUT` headers and `Content-Range: bytes 0-(n-1)/n`, `Content-Type` per container; generic stages preparing → uploading → final_chunk → finalizing (no new stage); `PUBLISH_COMPLETE` without post ID → `PUBLISHED`, attempt `succeeded`, trigger `manual`, `external_id`/`external_url` null, warning `tiktok_private_post_no_link`; exactly one post ID → `external_id`, no URL; `FAILED` with each `fail_reason` → determined failure with its code; polling waits follow research §15 with `FakeClock` and never exceed 30 reads/min; `submitted` contains no token, URL or `publish_id`; `refresh_details`/`release` are no-ops; minimal reconcile: `PUBLISH_COMPLETE` of the original `publish_id` → `PUBLISHED`, any other status → still uncertain, and it never calls `init`, `PUT` or list endpoints
- [X] T038 [P] [US6] Write `backend/tests/test_tiktok_anti_duplicates.py` (one test per guarantee): `video/init/` called at most once per attempt, also when `init` fails (5xx, timeout, 401); `publish_id` committed in `tiktok_publish_runs` before the first `PUT` (asserted from inside the fake `PUT` handler with a fresh session); a failed `publish_id` commit → no `PUT`, determined; write-ahead (attempt stage `final_chunk` + run `final_chunk_started_at`) committed before the last `PUT`; a failed write-ahead commit → no last `PUT`, determined; **last `PUT` semantics (pre-V1, final)**: `201` → normal polling; timeout, transport error, 5xx, 400, 403, 404, 416, lost and unexpected responses → the last chunk is never resent, no new `init`, only status reads of the original `publish_id`, `PUBLISH_COMPLETE` → success, `FAILED` → determined, `PROCESSING_UPLOAD` until the timeout → ambiguous **also after a 4xx**, status read error/unexpected status → ambiguous; `uploaded_bytes < total` never triggers a resend; no second `publish_id` is ever requested; no list/query endpoint other than status is ever called; digest mismatch of the bytes read during upload → no write-ahead and no last `PUT`; the upload reads the file only once (read spy) and never loads more than one chunk buffer
- [X] T039 [P] [US1] Write the pre-V1 end-to-end security tests in `backend/tests/test_tiktok_publish_secrets.py` after a successful single-chunk publish, a determined failure and an ambiguous last chunk (fake upload URL with a recognisable `upload_token`, fake tokens): a full SQLite dump contains no upload URL or any part of its query, no access/refresh token, client secret or `Authorization` value; responses of `tiktok-options`, `tiktok-creator-info`, `tiktok-consent`, `GET /publications/{id}`, `publish-check` and `GET /attempts` contain none of them and no `publish_id`; captured logs of all loggers (including `httpx`/`httpcore`) contain no upload URL, upload query/token, tokens or `Authorization`; `str()`/`repr()` of every exception raised by the gateway and every stored `error_message` contain no sensitive URL, token or raw TikTok body
### Implementation

- [X] T040 [US1] Implement the `TikTokPublisher` class (`accepts_text_only = False`, constructor with gateway, credential store and settings, `TikTokPayload` without secrets) and register it in `app.state.publishers[Platform.TIKTOK]` in `backend/app/main.py`
- [X] T041 [US4] Implement `TikTokPublisher.check()` (connection, `Content` video, file/size, video matrix, options, caption, consent fingerprint with `Content.checksum` — never re-hashing the file —; summary lines of contracts §5; no network) and `TikTokPublisher.prepare()` (Creator Info via `call_with_token` with one retry on 5xx/transport, creator can post, privacy offered and allowed, interactions compatible, duration ≤ creator max, streaming SHA-256 == `Content.checksum`, chunk plan, `post_info`/`source_info`, non-sensitive `submitted` snapshot including `consented_at`) in `backend/app/tiktok_publishing.py` (makes T036 pass)
- [X] T042 [US1] Implement `TikTokPublisher.upload()` up to and including the last `PUT` in `backend/app/tiktok_publishing.py`: create the run, fresh token, single `init_video_post`, commit `publish_id`, sequential intermediate chunks read once into buffers that feed `UploadDigest` (no retries yet), read the last chunk into memory, verify the full digest, write-ahead (generic + run), exactly one last `PUT`; then `enter_finalizing()` and run `processing` for **every** outcome of that `PUT` (`201` or not), storing the HTTP status only as diagnosis in `final_chunk_http_status` — no outcome of the last `PUT` other than `201` is interpreted, none is retried
- [X] T043 [US1] Implement status polling, status mapping (`PROCESSING_UPLOAD`, `PUBLISH_COMPLETE`, `FAILED`; timeout, read error or unexpected status after the write-ahead → ambiguous `tiktok_processing_pending`/`tiktok_result_uncertain`), outcome building and run closing, no-op `refresh_details`/`release`, and minimal `reconcile()` (only runs with `publish_id` and `final_chunk_started_at`; one status read; `PUBLISH_COMPLETE` → `Reconciliation`; anything else → `None`) in `backend/app/tiktok_publishing.py` (makes T037, T038 and T039 pass, together with T022)
- [X] T044 [P] [US2] Extract the inline `<video>`/image preview of `frontend/src/components/ContentDetail.tsx` into a neutral `frontend/src/components/MediaPreview.tsx` (same media URL logic, no redesign), use it in `ContentDetail.tsx` and in `TikTokPublishOptions.tsx` (extending `TikTokPublishOptions.test.tsx` with the video preview), and add `frontend/src/components/MediaPreview.test.tsx` plus a regression assertion that `ContentDetail` still renders the same preview (in `frontend/src/components/ContentLibrary.test.tsx` or a new `ContentDetail.test.tsx`)
- [X] T045 [US1] Integrate TikTok with the generic publish flow in `frontend/src/components/PublicationDetail.tsx` and `frontend/src/components/PublishNowDialog.tsx`: `Publish now` enabled by `publish-check`; for TikTok the dialog **always** shows the current declaration text and links with a mandatory checkbox (even when a consent with the same fingerprint already exists); confirming calls `confirmTikTokConsent` with the shown fingerprint/version and only then the generic publish; `409 tiktok_consent_stale` stops and asks to review; notice "TikTok may take a few minutes to process the video"; tests in `frontend/src/components/PublicationDetail.test.tsx` (checkbox required, consent call before publish, stale stops publishing, no TikTok checkbox for other platforms)
- [X] T046 Run the full backend suite, lint, format and type checks (`uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`) and the frontend checks (`npm test`, `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`); fix failures before V1

---

## Phase 5: ⛔ Checkpoint V1 — TikTok real (STOP de `/speckit-implement`)

**Depende de**: T001–T046 completas (publisher mínimo de un chunk implementado y en verde).

- [X] T047 [US1] **V1 REAL (manual, ejecutado por el usuario)**: run steps 1–20 of "V1 — Publisher mínimo real" in `specs/013-tiktok-direct-post/quickstart.md` with a small innocuous video and the real TikTok Sandbox (unaudited client, private target account): Creator Info, `SELF_ONLY`, private target, max duration, interaction flags, `init` with `FILE_UPLOAD`, request shape, `publish_id`, non-sensitive shape of `upload_url` (host and parameter names only), single-chunk upload, real `201`, real status sequence, `PUBLISH_COMPLETE`, observed `uploaded_bytes`, presence/absence of `publicaly_available_post_id`, private post visible in TikTok, security checks and zero duplicates. Record PASS/STOP in "Resultados". On PASS update research.md (§10 upload host/redaction, §12 `uploaded_bytes` semantics, §15 observed timings) and adjust `FakeTikTok`/gateway tests to the real shapes. On any STOP condition: **stop and revise spec/plan; do not continue**. **`/speckit-implement` ends here; continue with T048 only after V1 PASS.**

---

## Phase 6: Multi-chunk y subida avanzada (US7, P3)

**Goal**: vídeos grandes en varios chunks con reintentos acotados de chunks intermedios y
política conservadora de `416`, sin tocar las garantías del último chunk.

**Independent Test**: con `FakeTikTok` y constantes de chunk inyectadas (archivos de KB),
subir 2–5 chunks con `206`, `5xx` reintentado, `416` con y sin `Content-Range`, `400/403/404` y
deadline.

- [X] T048 [P] [US7] Write `backend/tests/test_tiktok_upload_errors.py`: multi-chunk happy path (sequential `206`s then `201`, `Content-Range` of every chunk, progress reported only on confirmed bytes, `confirmed_bytes` in the run); intermediate 5xx/transport/timeout/429 retried with waits 2, 5, 10 s on the same buffer then success; retries exhausted → determined `tiktok_upload_failed`, last chunk never sent; intermediate 400/404 → determined, 403 → `tiktok_upload_expired`, no retry; 416 whose response `Content-Range` reports `accepted_bytes == last + 1` of the expected total → continue with the next chunk; 416 without/other `Content-Range` (including `== last`, behind, ahead, other total) → determined before write-ahead; `upload_deadline` (50 min, `FakeClock`) exceeded before the write-ahead → `tiktok_upload_expired`; the digest is not updated twice for a retried buffer; the last chunk is never retried; the multi-chunk variant of the last-`PUT` semantics fixed in T038 (any non-`201`, including `4xx`, → polling of the original `publish_id` only; `PROCESSING_UPLOAD` stays ambiguous)
- [X] T049 [US7] Implement intermediate chunk retries, the `416` policy, upload deadline and progress/`confirmed_bytes` updates in `TikTokPublisher.upload()` in `backend/app/tiktok_publishing.py`
- [X] T050 [US7] Refine messages and diagnosis for last-chunk outcomes in multi-chunk uploads (diagnosis from `final_chunk_http_status`, user messages per research §19) in `backend/app/tiktok_publishing.py` **without changing the semantics of T042/T043**: one attempt, any non-`201` → only status of the original `publish_id`, `PUBLISH_COMPLETE` success, `FAILED` determined, everything else ambiguous; a `4xx` never makes `PROCESSING_UPLOAD` determined (makes T048 pass)

---

## Phase 7: Reconciliación, recuperación y errores (US6 + US8, P2/P3)

**Goal**: los resultados ambiguos se resuelven solo con el `publish_id` original; la extensión
neutral permite "confirmado no publicado"; reinicios y errores clasificados según la tabla.

**Independent Test**: interrumpir en cada fase y reconciliar con estados programados del fake;
provocar cada error de la taxonomía y comprobar código, determinación y efecto en la conexión.

### Tests (escribir primero; compatibilidad del núcleo antes de tocarlo)

- [X] T051 [P] [US6] Write `backend/tests/test_publish_reconcile.py` for the neutral core extension: a `FakePublisher.reconcile` returning `ReconciledFailure` makes the uncertain attempt determined with its code/message, the publication stays `FAILED`, `requires_remote_check` becomes false; `Reconciliation` keeps working; `None` and exceptions leave the attempt uncertain; nothing changes if the attempt or publication changed meanwhile; and the existing `backend/tests/test_instagram_reconcile.py` and `backend/tests/test_threads_reconcile.py` still pass unchanged
- [X] T052 [P] [US6] Extend `backend/tests/test_tiktok_reconcile.py`: `PUBLISH_COMPLETE` → `PUBLISHED` (published_at = write-ahead time, no URL); `FAILED` → determined via `ReconciledFailure` with mapped code; `PROCESSING_UPLOAD`, read error, `invalid_publish_id`, unexpected status → still ambiguous; only the original `publish_id` is read; zero `init`, `PUT` or list calls; runs without write-ahead are ignored; triggered by `GET publish-check` and `Publish now`; an unresolved ambiguous attempt still requires `confirm_remote_checked`
- [X] T053 [P] [US6] Write `backend/tests/test_tiktok_recovery.py`: restart (generic `recover_interrupted_attempts`) with no run / no `publish_id` → determined `interrupted`; `publish_id` without write-ahead → determined, upload not resumed and no new `init`; write-ahead reached (stage `final_chunk`) and during polling (stage `finalizing`) → ambiguous; shutdown (`should_stop`) during intermediate chunks → determined, during polling → ambiguous `tiktok_processing_pending`; polling timeout with `PROCESSING_UPLOAD` → ambiguous `tiktok_processing_pending`; `PROCESSING_DOWNLOAD`/`SEND_TO_USER_INBOX`/unknown → ambiguous `tiktok_result_uncertain` immediately; a later reconcile settles each ambiguous case
- [X] T054 [P] [US8] Write `backend/tests/test_tiktok_publish_errors.py`: `access_token_invalid` on Creator Info/status renews once via Feature 012; on `init` → determined `tiktok_unavailable` without a second `init`; `scope_not_authorized` anywhere → `tiktok_reconnect_required` and connection `reconnect_required`; `auth_removed` → determined and reconnect required; every temporary error (network, 5xx, 429) leaves the connection `connected`; after the write-ahead credential/read failures become ambiguous; every message is a fixed safe string without raw TikTok bodies; `log_id` only in logs

### Implementation

- [X] T055 [US6] Add `ReconciledFailure`, `persist_reconciled_failure` and the extended return type handling in `reconcile_uncertain` to `backend/app/publishing.py` without any TikTok reference (makes T051 pass)
- [X] T056 [US6] Complete `TikTokPublisher.reconcile()` (`ReconciledFailure` for `FAILED`, run phase/status updates staged in the reconciliation transaction) in `backend/app/tiktok_publishing.py` (makes T052 pass)
- [X] T057 [US6] Harden ambiguity classification in `upload()` (shutdown during polling, polling timeout, unexpected statuses, status read failures after the write-ahead) in `backend/app/tiktok_publishing.py` (makes T053 pass)
- [X] T058 [US8] Complete the error taxonomy and Feature 012 integration (`mark_scope_not_authorized`, `mark_reconnect_required` in a new session, no duplicated renewal logic) in `backend/app/tiktok_publishing.py` (makes T054 pass)

---

## Phase 8: Scheduler (US5, P2)

**Goal**: programar exige consentimiento vigente; una publicación armada con consentimiento
caducado se bloquea en `check()` sin red y vuelve a ser ejecutable al reconfirmar.

**Independent Test**: con reloj inyectable y fakes, armar, editar, ejecutar ciclos y comprobar
0 peticiones a TikTok mientras el consentimiento está caducado y una sola ejecución `scheduled` tras
reconfirmar.

### Tests (escribir primero; compatibilidad del núcleo antes de tocarlo)

- [X] T059 [P] [US5] Write `backend/tests/test_publish_arming.py` for the neutral hook: arming via `PATCH /api/publications/{id}` and creation with `auto_publish_enabled=true` call `Publisher.arming_problems`; a problem returns `409` on field `auto_publish_enabled`; batch creation for several accounts is all-or-nothing (one TikTok account with problems → `409`, no publication created for any account, one `fields[]` entry per affected TikTok account identifying it); YouTube, Instagram and Threads publishers return `[]` and keep their current arming behaviour (existing scheduler/automation tests unchanged)
- [X] T060 [P] [US5] Write `backend/tests/test_tiktok_scheduler.py`: arming without valid consent → `409 tiktok_consent_required`/`tiktok_options_incomplete`/`tiktok_caption_invalid`; creating an armed TikTok publication → `409 tiktok_consent_required`; armed publication runs once at its time with trigger `scheduled` and a fresh Creator Info request in `prepare`; **editing material metadata after arming keeps it `SCHEDULED` and armed, consent becomes `stale`, and at its time the cycle makes zero requests to `FakeTikTok`, creates no attempt, never reaches `PUBLISHING`, records the generic automatic error `tiktok_consent_required` with a local (non-TikTok) message and changes no option**; then, after that first failed preflight, reconfirming consent and advancing `FakeClock` by at least `AUTO_PUBLISH_RETRY_INTERVAL` (120 s) within the automatic window → the next eligible automatic retry publishes once without rescheduling (no TikTok-specific retry); changed rules at run time (privacy no longer offered, interaction disabled, max duration lowered) → determined preflight failure, options unchanged; pause blocks and resume runs within the window; manual `Publish now` vs scheduler race and two concurrent cycles start at most one execution; an ambiguous last attempt is never retried automatically
- [X] T061 [US5] Add `arming_problems(session, publication) -> list[PublishProblem]` to the `Publisher` protocol in `backend/app/publishing.py` and return `[]` in `backend/app/youtube_publishing.py`, `backend/app/instagram_publishing.py`, `backend/app/threads_publishing.py` and the test `FakePublisher` in `backend/tests/fakes.py`
- [X] T062 [US5] Call `arming_problems` through `app.state.publishers` in `_set_consent` and in publication creation with `auto_publish_enabled=true` in `backend/app/publications.py`, platform-neutral (makes T059 pass)
- [X] T063 [US5] Implement `TikTokPublisher.arming_problems` (options complete and valid, caption valid, consent valid for the current fingerprint; no network) and the local consent message used by `check()` in `backend/app/tiktok_publishing.py` (makes T060 pass)

---

## Phase 9: Frontend completo (US2 + US8)

**Goal**: revisión TikTok completa y conforme a la UX oficial, con explicaciones de todo lo
deshabilitado, estado del consentimiento y presentación clara de progreso, errores e historial.

- [X] T064 [US2] Extend `frontend/src/components/TikTokPublishOptions.test.tsx`: disclosure toggle OFF by default revealing `Your brand`/`Branded content`; labels "Promotional content"/"Paid partnership"; ON with none selected disables publishing with "You need to indicate if your content promotes yourself, a third party, or both."; `Branded content` disabled while `SELF_ONLY` is selected with "Branded content visibility cannot be set to private." and the unaudited explanation; declaration text/links switch with Branded content; `stale` consent shown with "confirm again" and the checkbox reset; warning when `account_appears_public`; blocked creator; armed publication with stale consent shows that it will not publish until reconfirmed; arming `409` messages shown; `integrity_warning` (`tiktok_video_changed` from the last attempt) shown until a later consent; consent wording never claims the current bytes are verified; plus, in `frontend/src/components/PublicationCreate.test.tsx`, a batch creation rejected with `409` shows which TikTok destination needs options/consent and nothing is created
- [X] T065 [US2] Implement the complete review in `frontend/src/components/TikTokPublishOptions.tsx`; and, only if the existing generic `409` handling does not yet show per-account `fields[]`, add the minimal support in `frontend/src/components/PublicationCreate.tsx` so that a batch creation where a TikTok account needs action shows which TikTok destination must complete/reconfirm its options, keeps the all-or-nothing behaviour and never creates publications partially; if `PublicationCreate.tsx` already shows those `fields[]` generically, leave it unchanged and note in the task that the `PublicationCreate.test.tsx` case passes with the existing behaviour (makes T064 pass). _Nota de implementación: `PublicationCreate.tsx` ya mostraba los `fields[]` de `account_ids` genéricamente; no se modificó._
- [X] T066 [P] [US8] Update `frontend/src/components/PublicationAttempts.tsx` and `frontend/src/components/PublicationAttempts.test.tsx` for TikTok: labels of the existing generic stages only (preparing, uploading with confirmed bytes, final_chunk, finalizing shown as "TikTok is processing"), no new stage, messages of every `tiktok_*` error code, ambiguous review text ("check your TikTok profile before publishing again"), `tiktok_processing_pending` with "check again", no "Open on TikTok" link without a URL
- [X] T067 [P] [US2] Extend `frontend/src/storage-safety.test.tsx` to assert no TikTok options, Creator Info, avatar URL, fingerprint or attempt data is written to `localStorage`/`sessionStorage`

---

## Phase 10: Seguridad, regresión y documentación (Polish)

- [X] T068 [P] Extend `backend/tests/test_tiktok_publish_secrets.py` (global, beyond the pre-V1 checks of T039) to multi-chunk uploads with retries, `416`, reconciliation, recovery and scheduled runs: after every scenario a full SQLite dump contains no upload URL (or its query), access/refresh token, client secret or `Authorization` value; responses of `tiktok-options`, `tiktok-creator-info`, `tiktok-consent`, publication, publish-check and attempts contain none of them and no `publish_id`; captured logs (all loggers, including `httpx`/`httpcore`) and exception strings contain no upload URL or token; no `MediaDeliveryProvider` is built or called for TikTok; no request goes to any video list endpoint
- [X] T069 [P] Run the regression suites and the architecture tests (`tests/test_publications_states.py`, YouTube, Instagram, Threads and Feature 012 `tests/test_tiktok_*` connection tests, scheduler/automation tests), add an explicit regression in `backend/tests/test_tiktok_oauth.py` that the requested TikTok scopes are exactly `user.info.basic` and `video.publish` (no `video.upload`, no `video.list`), review the code for hard-coded caps (L7), and fix any regression without adding TikTok logic to the core
- [X] T070 [P] Write `docs/tiktok-publishing.md`: Direct Post with `FILE_UPLOAD`, required options and consent (including the stale-consent behaviour of armed publications), unaudited client (`SELF_ONLY`, private account, dynamic caps), caption counting, video requirements and delegated checks, chunking, no link for private posts, ambiguous results and reconciliation, security of the upload URL, consent wording ("Consent recorded", integrity rechecked before publishing, `tiktok_video_changed` warning), the strict confirmation in the `Publish now` dialog and its conscious limitation (research §21: the backend only checks a valid fingerprint; a direct API call with a still-valid fingerprint has no extra "recent consent" check; acceptable only for the current local single-user model), the expected scheduler warning every automatic retry (currently 120 s) while an armed publication has stale consent inside its window, and the product risk on App Audit intended use
- [X] T071 [P] Add a "Publishing to TikTok" section to `README.md` linking `docs/tiktok-publishing.md` (scope, unaudited/private limitation, out-of-scope list)
- [X] T072 Update `specs/013-tiktok-direct-post/checklists/requirements.md` notes with any values confirmed in V1 and verify every FR of spec.md maps to a completed task
- [X] T073 Run the full backend and frontend checks (`uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; `npm test`, `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`) and report any failure

---

## Phase 11: Checkpoint V2 — TikTok real

- [X] T074 **V2 REAL (manual, ejecutado por el usuario)**: run steps 1–11 of "V2 — Validación final" in `specs/013-tiktok-direct-post/quickstart.md`: multi-chunk upload, real scheduled publication, stale-consent block and reconfirmation without rescheduling, pause/resume, controlled restart during polling and reconcile, Your brand, AIGC, security checks, regression smoke of the other platforms, the TikTok account still `Connected`, and manual deletion of every test post in TikTok. Do not provoke ambiguous results other than the controlled restart. Record PASS/STOP in "Resultados"; on STOP revise spec/plan

---

## Dependencies & Execution Order

- **Phase 0 (T001)** → **Phase 1 (T002–T005)** → **Phase 2 (T006–T023)** bloquea todo lo demás.
- **Phase 3 (US2/US3)** depende de Phase 2. **Phase 4** depende de Phase 2 y de T029–T031
  (opciones y consentimiento) para preparar publicaciones; T044 y T045 dependen de T035; T043 hace pasar T037–T039 junto con T022.
- **Phase 5 / T047 (V1)** depende de **T001–T046**. ⛔ `/speckit-implement` se detiene aquí.
- Tras V1 PASS: **Phase 6 (US7)**, **Phase 7 (US6/US8)** y **Phase 8 (US5)** dependen de Phase 4 y
  son independientes entre sí salvo: T056 depende de T055; T057 conviene tras T050 (comparten
  `upload()` en el mismo archivo: ejecutar Phase 6 y Phase 7 de forma secuencial en
  `tiktok_publishing.py`).
- **Phase 9** depende de Phase 3 (y de Phase 8 para los mensajes de armado de T064).
- **Phase 10** depende de Phases 6–9. **Phase 11 / T074 (V2)** depende de T073.

### Dentro de cada fase

Tests primero (deben fallar) → implementación → tests dirigidos en verde. Cambios del núcleo
(T055, T061–T062) solo después de sus tests de compatibilidad (T051, T059).

## Parallel Example: Foundational

```text
T006 test_tiktok_caption.py   T007 test_tiktok_chunks.py   T008 test_tiktok_video_rules.py
T009 test_tiktok_option_rules.py   T010 test_tiktok_fingerprint.py   T011 test_tiktok_gateway_post.py
T012 test_tiktok_errors.py   T013 test_tiktok_publish_secrets.py   T014 test_publications_states.py
(después: T015–T019 secuenciales en tiktok_media.py; T020, T022 y T023 en paralelo con ellos)
```

## Parallel Example: Phase 3

```text
T024 test_tiktok_options.py   T025 test_tiktok_consent.py   T026 test_tiktok_creator_info.py
T027 test_tiktok_caption_preview.py   T028 utils.test.ts   T032 utils.ts   T033 types/api/fake api
```

## Parallel Example: Phase 7

```text
T051 test_publish_reconcile.py   T052 test_tiktok_reconcile.py
T053 test_tiktok_recovery.py     T054 test_tiktok_publish_errors.py
```

## Implementation Strategy

### Bloque 1 → V1 (MVP real)

1. Phases 0–2: precondiciones, base de datos, reglas puras, gateway, taxonomía, redacción.
2. Phase 3: revisión mínima con Creator Info, opciones, caption y consentimiento.
3. Phase 4: publisher manual de un chunk con todas las garantías del punto irreversible; suite
   completa (T046).
4. **T047 V1 con TikTok real. STOP.** Ajustar research/fakes a lo observado o revisar el diseño.

### Bloque 2 → V2

5. Phase 6 (multi-chunk) → Phase 7 (reconcile/recovery/errores) → Phase 8 (scheduler) →
   Phase 9 (frontend completo) → Phase 10 (seguridad, regresión, docs, checks).
6. **T074 V2 con TikTok real**; borrar los posts de prueba.

## Notes

- `[P]` = archivo distinto y sin dependencias pendientes; las tareas sobre
  `backend/app/tiktok_media.py` y `backend/app/tiktok_publishing.py` son secuenciales.
- No se crean archivos de GB: los tamaños grandes se cubren con `plan_chunks` puro y constantes
  inyectables.
- Commits pequeños en inglés solo cuando el usuario lo pida.
