---

description: "Task list for Telegram User Account & Publishing (Feature 015)"
---

# Tasks: Telegram User Account & Publishing

**Input**: Design documents from `specs/015-telegram-user-publishing/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige (FR-036), pero **solo para código propio de AutoPublisher**.
Offline con `FakeTelegramGateway`, `InMemoryCredentialStore` y `sleep` instantáneo. Nada de
tests de Telethon/MTProto/chunking/sesiones de Telethon ni de cada error RPC. Los tests de cada
fase se escriben primero. Durante el desarrollo solo tests dirigidos
(`uv run pytest tests/test_telegram_*.py`, `npx vitest run src/components/TelegramConnectionPanel.test.tsx`);
la suite completa y los quality gates **solo en T035** (y CI).

**Organization**: fases según plan.md (fundación → cuenta + V1a → publicación + V1b → UI →
scheduler → cierre). Código, comentarios, mensajes de API/UI, docs y commits en inglés.

> ## ⛔ Límites de `/speckit-implement`
>
> 1. **STOP en T018 (V1a)**: login real, Verify, sesión solo en el almacén seguro y canal real
>    listado. Continuar solo con PASS registrado en `quickstart.md → Resultados`. Si la sesión
>    no puede guardarse de forma segura o el canal no se identifica bien: STOP y revisar
>    spec/plan.
> 2. **STOP en T028 (V1b)**: texto, imagen + caption y vídeo + caption reales, sin bot visible y
>    con apariencia normal del canal. **No** continuar con UI/scheduler/polish sin **V1 PASS**.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivo distinto, sin dependencias pendientes).
- **[Story]**: US1 conexión/V1a · US2 publicación/V1b · US3 canal destino · US4 scheduler ·
  US5 Verify/Disconnect · US6 anti-duplicados · US7 errores/FloodWait.

## Path Conventions

Backend en `backend/app/` y `backend/tests/`; frontend en `frontend/src/`; docs en `docs/`.

---

## Phase 1: Setup

- [X] T001 Add `telethon>=1.45,<2` to `backend/pyproject.toml` dependencies, add a mypy override (`module = ["telethon", "telethon.*"]`, `ignore_missing_imports = true`) and refresh `backend/uv.lock` with `uv lock`
- [X] T002 [P] Add `telegram-app*.json`, `*.session` and `*.session-journal` to `.gitignore` (research §3, §5)
- [X] T003 [P] Add `get_telegram_app_file()` (`AUTOPUBLISHER_TELEGRAM_APP_FILE`, default `backend/data/telegram-app.json`) and `TELEGRAM_LOGIN_TTL = timedelta(minutes=10)` to `backend/app/config.py`, and `TELEGRAM_SERVICE = "autopublisher.telegram"` to `backend/app/credential_store.py`

---

## Phase 2: Foundational (bloquea todas las historias)

- [X] T004 Add `TelegramConnectionStatus` and `TelegramConnection` (table `telegram_connections`, fields and CHECKs exactly as data-model.md) to `backend/app/models.py`, plus migration `backend/migrations/versions/0014_create_telegram_connections.py`
- [X] T005 [P] Add Telegram schemas to `backend/app/schemas.py`: `TelegramConnectionRead` (with `identity`, `channel`, `channel_change_blocked`, `login`, `rate_limited_until`), `TelegramLoginStartWrite`, `TelegramLoginCodeWrite`, `TelegramLoginPasswordWrite`, `TelegramChannelRead`, `TelegramChannelsRead`, `TelegramChannelWrite` (contracts/api.md); no field may carry session, `api_hash`, `access_hash` or the full phone
- [X] T006 Create `backend/app/telegram_gateway.py` skeleton: `TelegramAppConfig`, `TelegramIdentity`, `TelegramChannel` (with internal `access_hash`), `PendingLogin`, `SignedIn`, `PasswordRequired`, `SendSpec`, `SendResult`, own exceptions (`TelegramUnauthorized`, `TelegramChannelUnavailable`, `TelegramTextRejected`, `TelegramMediaRejected`, `TelegramRateLimited(seconds)`, `TelegramLoginInvalid(reason)`, `TelegramUnavailable`, `TelegramUnconfirmed`), the `TelegramGateway` Protocol (plan.md) and a `_client(config, session)` factory that always passes `flood_sleep_threshold=5`, `request_retries=3`, `raise_last_call_error=True`, `receive_updates=False`, `device_model="AutoPublisher"`; this is the only module importing Telethon; set the `telethon` logger to WARNING
- [X] T007 [P] Create `backend/tests/fakes_telegram.py` with `FakeTelegramGateway` implementing the Protocol: scripted login steps (2FA on/off, invalid code), identity, channel list, scripted publish outcomes per call (confirmed, lost response, `RANDOM_ID_DUPLICATE`, flood wait, unauthorized, channel unavailable), records every `random_id` and spec sent, and an optional `threading.Event` to hold an operation open (for lock tests)
- [X] T008 Add `account_session(account_id, *, wait, should_stop=None)` to new `backend/app/telegram_connections.py`: per-`account_id` `threading.Lock` registry (guarded by a global lock); `wait=False` raises `409 telegram_busy`; `wait=True` polls `acquire(timeout=1)` and gives up if `should_stop()`; always releases in `finally` (research §2)
- [X] T009 Wire Telegram in `backend/app/main.py`: `create_app(telegram_credential_store=..., telegram_gateway=...)`, `KeyringCredentialStore(TELEGRAM_SERVICE)` by default, `TelethonGateway()` by default, a `TelegramLoginRegistry` on `app.state`, and include the `telegram_connections` router; add a `telegram_client` fixture in `backend/tests/conftest.py` using `FakeTelegramGateway`, `InMemoryCredentialStore` and a temporary `telegram-app.json`
- [X] T010 Test `account_session` in `backend/tests/test_telegram_connections.py`: only one holder per account; released after an exception; `wait=False` → `telegram_busy` while held; `wait=True` waits and proceeds after release; another account is not blocked

**Checkpoint**: modelo, migración, gateway (esqueleto), fake, lock y wiring listos.

---

## Phase 3: Cuenta real + canal (US1, US3, US5-Verify) — Checkpoint V1a

**Goal**: conectar la cuenta real (teléfono → código → 2FA), verificarla, listar y elegir el
canal, con la sesión solo en el almacén seguro.

**Independent Test**: con el fake: login completo y con 2FA, Verify, listado y selección;
con la cuenta real: quickstart V1a.

### Tests (primero)

- [X] T011 [P] [US1] Login tests in `backend/tests/test_telegram_connections.py`: start → code → `connected` with identity; start → code → `password` step → `connected`; invalid code → `422 telegram_login_invalid`; code without pending login / after TTL / after cancel → `409 telegram_login_not_pending`; reconnect with a different user ID → `409 telegram_identity_mismatch`; missing `telegram-app.json` → `503 telegram_not_configured`; non-Telegram account → `409 platform_not_supported`; session, `api_hash`, code and password absent from SQLite, every response and captured logs, and stored only in the in-memory credential store
- [X] T012 [P] [US3] Channel tests in `backend/tests/test_telegram_connections.py`: `GET .../channels` returns only what the gateway marks eligible, never `access_hash`; `PUT .../channel` stores id, access hash and title; not eligible → `422 telegram_channel_not_eligible`; with a `scheduled` or `publishing` Telegram publication of the account → `409 telegram_channel_change_blocked` and `channel_change_blocked = true` in the read; Verify, channels and channel change → `409 telegram_busy` while the account lock is held
- [X] T013 [P] [US5] Verify tests in `backend/tests/test_telegram_connections.py`: valid session refreshes name/username and `last_verified_at`; `TelegramUnauthorized` or different user ID → `200` with `status = "reconnect_required"`; no connection → `409 telegram_not_connected`
- [X] T014 [P] [US3] Test in `backend/tests/test_telegram_gateway.py` (own code only, Telethon types built in memory, no network): the channel eligibility helper keeps broadcast channels where the user is creator or has `post_messages`, and drops megagroups, left channels, users and channels without permission; `_client()` is built with `flood_sleep_threshold == 5`

### Implementación

- [X] T015 [US1] Implement login in `backend/app/telegram_connections.py`: `load_config()`, in-memory `TelegramLoginRegistry` (step, partial session, phone, `phone_code_hash`, `expires_at`; masked `phone_hint`), routes `login/start`, `login/code`, `login/password`, `login/cancel`, storing `{"v":1,"session","user_id"}` under a new `credential_ref` and creating/updating the `TelegramConnection` row, all under `account_session(..., wait=False)`; error mapping per contracts/api.md (FloodWait → `429 telegram_rate_limited`)
- [X] T016 [US1] Implement `GET /api/accounts/{id}/telegram-connection`, `connection_to_read()` (including `channel_change_blocked` and `rate_limited_until`), `load_session()`, `mark_reconnect_required()` and `POST .../verify` in `backend/app/telegram_connections.py`
- [X] T017 [US3] Implement `GET .../channels` and `PUT .../channel` (re-list on the server, take `access_hash` from there, block rule against `Publication` rows in `scheduled`/`publishing` for the account) in `backend/app/telegram_connections.py`, and the real account operations of `TelethonGateway` (`send_code`, `sign_in_code`, `sign_in_password`, `get_me`, `log_out`, `list_channels` + eligibility helper) in `backend/app/telegram_gateway.py`, each via `asyncio.run` with a short-lived client and error translation (research §2, §4, §6, §7, §12)
- [X] T018 ⛔ **V1a (manual, user)**: follow quickstart.md → V1a with the real account and `curl` (login, 2FA if any, Verify, identity, channel listed and selected, no session in SQLite/files/logs, "AutoPublisher" in Telegram active sessions); record PASS/FAIL in `specs/015-telegram-user-publishing/quickstart.md` → `## Resultados`. **STOP**: do not continue without PASS

---

## Phase 4: Publicación real (US2, US6, US7) — Checkpoint V1b

**Goal**: publicar texto, una imagen y un vídeo MP4 con caption en el canal, con `random_id`
estable, confirmación por `UpdateMessageID`, resultado incierto cuando no hay confirmación y
errores sencillos.

**Independent Test**: con el fake: Publish Now de los tres tipos y escenarios de duplicado y
error; con la cuenta real: quickstart V1b.

### Tests (primero)

- [ ] T019 [P] [US2] Publishing tests in `backend/tests/test_telegram_publishing.py`: text post via existing `POST /api/projects/{id}/text-publications` and Publish Now; image and MP4 video with caption via existing content publications; text/caption sent exactly (description + hashtags, no title); `external_id` = message ID; `external_url` only for a public channel username; preflight problems `telegram_not_connected`, `telegram_reconnect_required`, `telegram_channel_required`, `telegram_text_invalid`, `telegram_text_too_long` (UTF-16 count, 4096/1024), `telegram_media_unsupported` (MOV/WEBM, photo dimensions), `telegram_file_too_large`, `media_unavailable`; while another operation holds the account lock, Publish Now waits and then completes
- [ ] T020 [P] [US6] Anti-duplicate tests in `backend/tests/test_telegram_publishing.py`: `telegram_random_id` is already persisted in the attempt's `submitted` when the fake's send is called; `TelegramUnconfirmed` → attempt failed with `outcome_determined = false` and publication requires the generic remote check (never `PUBLISHED` without message ID); after that uncertain attempt, the next attempt of the same publication sends the **same** `random_id`
- [ ] T021 [P] [US6] Tests in `backend/tests/test_telegram_gateway.py` for the Telethon-free confirmation loop (`send_with_confirmation`) and the `UpdateMessageID` matcher: confirmed → message ID; lost response then confirmed → resent with the same `random_id`; `RANDOM_ID_DUPLICATE` → resent with the same `random_id`, never immediate success; original message returned on repetition → success with its ID; still unconfirmed after the bounded repetitions (2 extra, waits 3 s and 10 s via injected sleep) → `TelegramUnconfirmed`; `before_send()` returning `False` → nothing sent
- [ ] T022 [P] [US7] Error tests in `backend/tests/test_telegram_publishing.py`: `TelegramRateLimited(120)` → attempt `telegram_rate_limited` (determined), `flood_wait_until` stored, and `publish-check` reports `telegram_rate_limited` until it passes; `TelegramUnauthorized` → `telegram_reconnect_required` and connection `reconnect_required`; `TelegramChannelUnavailable` → `telegram_channel_unavailable`; `TelegramUnavailable` before `finalizing` → determined `telegram_unavailable`; no secret in attempt rows or logs

### Implementación

- [ ] T023 [US6] Implement in `backend/app/telegram_gateway.py` the Telethon-free `send_with_confirmation(send_once, random_id, waits, sleep)` and the `UpdateMessageID` matcher (research §8.4–§8.6)
- [ ] T024 [US2] Implement `TelethonGateway.publish()` in `backend/app/telegram_gateway.py`: one short-lived client that reads the channel (`channels.getChannels`, permission, title, username), uploads with `upload_file(progress_callback=...)` (aborting if `should_stop()`), calls `before_send()`, builds `SendMessageRequest` or `SendMediaRequest` (`InputMediaUploadedPhoto`; `InputMediaUploadedDocument` `video/mp4` with `DocumentAttributeVideo(duration, w, h, supports_streaming=True)` and `DocumentAttributeFilename("video.mp4")`) with the given `random_id`, and sends through `send_with_confirmation`; translate errors per research §12
- [ ] T025 [US2] Create `backend/app/telegram_publishing.py` with `TelegramPublisher` (`accepts_text_only = True`): `check()` (type, limits, formats, sizes, file, connection, channel, `flood_wait_until`; summary per contracts/api.md), `prepare()` without network (load session, new or reused `random_id` per research §8.1–§8.2, `submitted` with `post_type`, `channel_id`, `channel_title`, `text_length`, `telegram_random_id`), `arming_problems()` (not connected / no channel)
- [ ] T026 [US2] Implement `upload()` in `backend/app/telegram_publishing.py` inside `account_session(account_id, wait=True, should_stop=reporter.should_stop)`, with progress, `before_send=reporter.enter_finalizing`, refresh of channel title/username in the row, outcome (`external_id`, `external_url`, `details`), error → `PublishFailure` mapping (`TelegramUnconfirmed` → `determined=False`), `flood_wait_until` and `reconnect_required` updates; `refresh_details()` returns the outcome, `release()` → `[]`, `reconcile()` and `follow_up()` → `None`
- [ ] T027 [US2] Register `Platform.TELEGRAM: TelegramPublisher(...)` in `backend/app/main.py`
- [ ] T028 ⛔ **V1b (manual, user)**: follow quickstart.md → V1b with the real channel (text, small JPEG + caption, small MP4 + caption via API Publish Now; check in Telegram: no bot, no "via", no AutoPublisher mark, normal channel appearance, video preview; message ID and public link saved); record results in `quickstart.md` → `## Resultados`; delete the test messages manually. **STOP**: no UI/scheduler/polish without **V1 PASS**

---

## Phase 5: Disconnect y UI (US5, US1, US3)

**Goal**: Disconnect seguro y panel mínimo en la app.

**Independent Test**: tests dirigidos de Disconnect y del panel.

- [ ] T029 [US5] Implement and test `POST .../disconnect` in `backend/app/telegram_connections.py` and `backend/tests/test_telegram_connections.py`: `log_out` then delete secret then row; already revoked session (`TelegramUnauthorized`) still removes locally; `TelegramUnavailable` → `503 telegram_unavailable` and nothing deleted; credential store failure → `503 credential_store_unavailable` and row kept; lock held → `409 telegram_busy`; idempotent without connection; also discards a pending login
- [ ] T030 [P] [US1] Add Telegram types (`TelegramConnection`, `TelegramChannel`, statuses) to `frontend/src/types.ts` (and `"telegram"` in `TEXT_POST_PLATFORMS`) and the telegram-connection calls to `frontend/src/api.ts`
- [ ] T031 [US1] Create `frontend/src/components/TelegramConnectionPanel.tsx` (status and identity; phone → code → password steps with cancel; Verify; Disconnect; channel selector disabled with the blocked explanation when `channel_change_blocked`; `telegram_busy`/rate-limit messages), mount it in `frontend/src/components/AccountList.tsx`, and add `"telegram"` to `PUBLISHING_PLATFORMS` in `frontend/src/components/PublicationDetail.tsx`
- [ ] T032 [P] [US1] Add `frontend/src/components/TelegramConnectionPanel.test.tsx` (with `frontend/src/test-fake-api.ts` additions): connect flow with 2FA, channel selection, blocked channel change message, Disconnect

---

## Phase 6: Scheduler (US4)

**Goal**: la misma publicación funciona programada con el scheduler genérico.

- [ ] T033 [US4] Test in `backend/tests/test_telegram_publishing.py` that an armed scheduled Telegram publication is executed by the generic scheduler through the same `TelegramPublisher` (`SCHEDULED → PUBLISHING → PUBLISHED`, attempt trigger `scheduled`) and that a scheduled run waits for the account lock like Publish Now; no scheduler/core change expected (fix only inside the Telegram integration if it fails)

---

## Phase 7: Polish

- [ ] T034 [P] Write `docs/telegram.md` (app credentials from my.telegram.org, `telegram-app.json`, connect flow, channel rule, supported content and limits, duplicates and uncertain results, FloodWait, Disconnect semantics, V1 limitations, native scheduling as future idea) and link it from `README.md`
- [ ] T035 Run the full quality gates once (`uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest`, `npm run lint`, `npm run build`, `npm test`), fix failures, then do the post-V1 validation in quickstart.md (real scheduled text, blocked channel change, `telegram_busy` while uploading, real Disconnect) and record it in `quickstart.md` → `## Resultados`

---

## Dependencies & Execution Order

- **Setup (T001–T003)** → **Foundational (T004–T010)** → **Phase 3 (T011–T017)** →
  **⛔ T018 V1a** → **Phase 4 (T019–T027)** → **⛔ T028 V1b** → Phase 5 → Phase 6 → Phase 7.
- T006 before T007, T015–T017, T023–T024. T008 before T010, T015–T017, T026, T029.
- T025 before T026 before T027. T023 before T024.
- T030 before T031 before T032.
- US4 (T033) depends on US2 being complete; US5 Disconnect (T029) only on Phase 3.

## Parallel Opportunities

- Setup: T002 ∥ T003. Foundational: T005 ∥ T007 (after T004/T006).
- Phase 3 tests: T011 ∥ T012 ∥ T013 ∥ T014.
- Phase 4 tests: T019 ∥ T020 ∥ T021 ∥ T022.
- Phase 5: T029 (backend) ∥ T030 (frontend); T032 after T031. Polish: T034 ∥ T033.

## Implementation Strategy

1. **MVP = V1 PASS** (T001–T028): cuenta real conectada y los tres tipos publicados con
   Publish Now vía API. Es el punto de decisión de la feature.
2. Después: Disconnect + UI (Phase 5), scheduler (Phase 6), docs y quality gates (Phase 7).
3. Commits pequeños por bloque (fundación, cuenta, publicación, UI, scheduler, docs), en inglés.

## Notas de tamaño

35 tareas, dentro del rango orientativo. Lo que no se crea a propósito: tests de Telethon,
MTProto, chunking o sesiones; un test por cada error RPC; tablas de opciones por publicación;
reconciliación; batería de concurrencia (un test de lock + tres comprobaciones de
`telegram_busy`/espera repartidas en T010, T012, T019, T029, T033).
