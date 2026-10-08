---

description: "Task list for the Instagram account connection (Instagram API with Instagram Login) feature"
---

# Tasks: Conexión de cuentas reales de Instagram mediante Instagram Login

**Input**: Design documents from `specs/008-instagram-oauth-connection/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-051, SC-010). Ningún test usa Meta real,
Internet ni el keyring real: se usa `FakeMeta` (`httpx.MockTransport`) y
`InMemoryCredentialStore`, y el fixture autouse `isolate_system_keyring` de
`backend/tests/conftest.py` sigue instalando un backend que falla. En cada historia los tests
se escriben primero y deben fallar antes de implementar.

**Organization**: tareas agrupadas por historia de usuario (US1–US7 de la spec). Código,
comentarios, mensajes de API/UI, README, docs y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes).
- **[Story]**: historia de usuario (US1–US7).

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`.
- Frontend: `frontend/src/`, `frontend/src/components/`.
- Comandos de backend desde `backend/`; de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- **Protocolo** (research §2–§8, no inventar nada más):
  - autorización: `https://www.instagram.com/oauth/authorize` con `client_id`,
    `redirect_uri`, `response_type=code`,
    `scope=instagram_business_basic,instagram_business_content_publish`, `state`,
    `force_reauth=true`; **sin PKCE**, sin `enable_fb_login`;
  - código → token corto: `POST https://api.instagram.com/oauth/access_token` (form:
    `client_id`, `client_secret`, `grant_type=authorization_code`, `redirect_uri`, `code`);
    respuesta con o sin envoltorio `data[0]`; campo `permissions` obligatorio;
  - corto → largo: `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=…&access_token=…`
    (sin versión);
  - renovación: `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=…`
    (sin versión, sin app secret);
  - identidad: `GET https://graph.instagram.com/v26.0/me?fields=user_id,id,username,account_type,profile_picture_url&access_token=…`;
    `GRAPH_API_VERSION = "v26.0"` como constante única, solo para endpoints versionados.
- **Identidad**: `user_id` de `/me` es la identidad autoritativa (`instagram_user_id`);
  nunca el username. `account_type` normalizado a `BUSINESS` | `MEDIA_CREATOR`.
- **Secretos**: token (corto y largo), código, `state`, app secret, cabeceras
  `Authorization` y URLs con secretos **nunca** aparecen en SQLite, logs, mensajes de
  excepción o de error, respuestas JSON, `localStorage`/`sessionStorage`. Solo el token largo
  se guarda, y solo en el keyring (servicio `autopublisher.instagram`). Sin fallback inseguro.
  **Única excepción** (spec FR-026): el `state` aparece solo dentro de la `authorization_url`
  de `authorize`; la redirect URL pegada (con `code` y `state`) solo vive en la memoria del
  formulario y viaja en el cuerpo del POST de `complete`, y el frontend la descarta en cuanto
  la envía.
- **Redirect URL**: no existe servidor HTTPS de callback. "Callback"/"redirect" en la spec es
  la redirect URL que produce Meta; el usuario la copia del navegador y la envía con
  `complete`. `complete`, `confirm` y `cancel` devuelven el resultado del intento de forma
  síncrona; **no** se crea ninguna ruta `GET` de intentos.
- **Verify connection**: solo en `connected` y con `Account` y proyecto activos; sobre
  `reconnect_required` → `409 instagram_reconnect_required` sin llamar a Meta; no existe
  transición a `connected` mediante Verify.
- **Clasificación semántica**: solo `instagram_gateway.py` interpreta números de error de
  Meta; el servicio trabaja con `MetaUnavailable`, `MetaTokenInvalid`, `MetaPermissionDenied`,
  `MetaRejected` y `MetaUnexpectedResponse`. No existe el código público
  `instagram_token_refresh_failed`.
- **Errores**: formato existente `{"error": {"code", "message", "fields"}}` con los códigos y
  estados HTTP de [contracts/api.md](contracts/api.md). Los códigos `instagram_*` se lanzan
  con `AppError(status, code, message)`; solo se reutilizan los genéricos existentes
  (`not_found`, `platform_not_supported`, `project_inactive`, `account_inactive`). Ninguna
  respuesta incluye datos crudos de Meta.
- **Fallos temporales** (transporte, timeout, 5xx, 429, límites de peticiones; clasificados
  como `MetaUnavailable`) **nunca** cambian el estado de conexión (`instagram_unavailable`).
  Rechazos definitivos de credencial o renovación → `instagram_reconnect_required`.
- **Sin revocación remota**: ningún código contacta con Meta al desconectar.
- **Núcleo independiente**: `backend/app/accounts.py`, `Account`, `AccountRead` y el código
  de YouTube **no se modifican** (salvo la constante nueva en `credential_store.py` y el
  registro en `main.py`). `Account` no declara relación con `InstagramConnection`.
- **Sin publicación**: no se registra ningún `InstagramPublisher` en `app.state.publishers`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: protección del repositorio y configuración base.

- [X] T001 Add Instagram-specific secret patterns `instagram-app*.json` and `meta-app*.json` under the "Secrets and credentials" section of `.gitignore`
- [X] T002 [P] Add `get_instagram_app_file()` (default `BACKEND_DIR / "data" / "instagram-app.json"`, overridable with `AUTOPUBLISHER_INSTAGRAM_APP_FILE`), `INSTAGRAM_ATTEMPT_TTL = timedelta(minutes=10)` and `INSTAGRAM_ATTEMPT_RETENTION = timedelta(minutes=10)` to `backend/app/config.py`
- [X] T003 [P] Add `INSTAGRAM_SERVICE = "autopublisher.instagram"` next to `SERVICE` in `backend/app/credential_store.py` (no logic changes; `KeyringCredentialStore(service=...)` is reused)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: persistencia, módulos puros, gateway, fakes y composición. Bloquea todas las
historias.

### Tests fundacionales (escribir primero)

- [X] T004 [P] Add `FakeMeta` to `backend/tests/fakes.py`: an `httpx.MockTransport` that serves the token endpoint (`POST api.instagram.com/oauth/access_token`), `GET graph.instagram.com/access_token`, `GET graph.instagram.com/refresh_access_token` and `GET graph.instagram.com/v26.0/me`; configurable identity (`user_id`, `id`, `username`, `account_type`, `profile_picture_url`), granted `permissions`, response shape (with/without `data`), long-lived `expires_in`, per-endpoint faults (transport error, 5xx, 429, Graph error codes 4/17/190/10/200, `OAuthException` on code exchange, malformed JSON, missing fields), recorded requests, and constants `FAKE_IG_CODE`, `FAKE_IG_SHORT_TOKEN`, `FAKE_IG_LONG_TOKEN`, `FAKE_IG_REFRESHED_TOKEN`, `FAKE_IG_APP_SECRET`; plus `instagram_app_config_json()` helper
- [X] T005 [P] Add fixtures to `backend/tests/conftest.py`: `instagram_app_file` (writes the config to `tmp_path` and sets `AUTOPUBLISHER_INSTAGRAM_APP_FILE`), `instagram_credential_store` (`InMemoryCredentialStore`), `fake_meta`, `instagram_client` (`create_app(..., instagram_credential_store=..., instagram_transport=fake_meta.transport())`), helpers `create_instagram_account(...)`, `start_instagram_authorization(...)` returning `(attempt_id, state)` parsed from `authorization_url`, `redirect_url_for(state, code=FAKE_IG_CODE)` and `complete_instagram(...)`; make every existing `create_app` call in `conftest.py` pass an `InMemoryCredentialStore` for `instagram_credential_store`
- [X] T006 [P] Write `backend/tests/test_instagram_oauth.py`: config loading (missing file, invalid JSON, empty `app_id`/`app_secret`, non-https or fragment `redirect_uri` → `InstagramOAuthNotConfigured`; `app_secret` absent from `repr`); `build_authorization_url` exact params (scopes comma-separated, `force_reauth=true`, no `code_challenge`); `parse_redirect_url` for the pasted redirect URL (success with `#_`, `error=access_denied`, other `error`, different host/path/scheme → invalid, trailing-slash tolerance, missing `code` and `error` → invalid); `InstagramAttemptRegistry` (latest-attempt-wins, TTL expiry, mismatched `state` does not consume, correct `state` consumed once, constant-time comparison via `secrets.compare_digest`, terminal retention and purge, `await_confirmation`/`claim_confirmation` once, `cancel` idempotent, `expire_for_account`, secrets cleared on finish)
- [X] T007 [P] Write `backend/tests/test_instagram_gateway.py` against `FakeMeta`: code exchange form fields and both response shapes; missing `access_token`/`permissions` → `MetaUnexpectedResponse`; `OAuthException` → `MetaRejected`; long-lived exchange params and `expires_at = now + expires_in`; refresh params (no app secret); `/me` uses `v26.0` and parses identity with `account_type` normalization; error classification table of research §9 (transport/5xx/429/4/17/32/613 → `MetaUnavailable`, 190 → `MetaTokenInvalid`, 10/2xx → `MetaPermissionDenied` carrying the affected permission only when Meta states it safely and it is one of the two required ones, other 4xx → `MetaRejected`, bad JSON → `MetaUnexpectedResponse`); these numeric mappings are tested only here; exception messages never contain tokens, URLs or response bodies and are raised `from None`; `InstagramToken.to_json/from_json` round trip and rejection of invalid stored JSON
- [X] T008 [P] Add `test_migration_0007_creates_instagram_connections` to `backend/tests/test_migrations.py`: table, CHECK constraints, `UNIQUE(account_id)`, `UNIQUE(project_id, instagram_user_id)`, `UNIQUE(credential_ref)`, upgrade/downgrade
- [X] T009 [P] Extend `backend/tests/test_accounts.py`: rename/extend the architecture test so `accounts.py` imports nothing containing `youtube` or `instagram`, `models.Account` has no `instagram_connection` attribute, and `AccountRead` fields stay unchanged for Instagram accounts

### Implementación fundacional

- [X] T010 Add `InstagramConnectionStatus` (`connected`, `reconnect_required`), `InstagramAccountType` (`BUSINESS`, `MEDIA_CREATOR`) and `InstagramConnection` (fields of data-model.md, no relationship on `Account`) to `backend/app/models.py`
- [X] T011 Create migration `backend/migrations/versions/0007_create_instagram_connections.py` (revises `0006`) with the columns, CHECK constraints, foreign keys (`RESTRICT`) and unique constraints of data-model.md
- [X] T012 [P] Add `InstagramIdentityRead`, `InstagramConnectionRead` (`status`, `identity`, `connected_at`, `last_verified_at`, `access_expires_at`, `oauth_configured`), `InstagramAuthorizeRead`, `InstagramOAuthAttemptRead` and `InstagramCompleteWrite` (`redirect_url`, max length 4096) to `backend/app/schemas.py`
- [X] T013 [P] Create `backend/app/instagram_oauth.py`: `MetaAppConfig` (secret with `repr=False`), `InstagramOAuthNotConfigured`, `load_meta_app_config(path)`, `SCOPES`/`REQUIRED_PERMISSIONS`, `generate_state()`, `build_authorization_url(config, state)`, `RedirectResult` + `parse_redirect_url(pasted, config)`, `InstagramIdentity` dataclass, `InstagramAttemptStatus`, `InstagramOAuthAttempt` (`to_read()` without secrets) and `InstagramAttemptRegistry` (research §11; no lookup route is exposed)
- [X] T014 [P] Create `backend/app/instagram_gateway.py`: endpoint constants, `GRAPH_API_VERSION = "v26.0"`, `ShortLivedToken`, `InstagramToken` (`issued_at`, `expires_at`, `permissions`, `to_json`/`from_json`), exceptions `MetaError`/`MetaUnavailable`/`MetaTokenInvalid`/`MetaPermissionDenied` (optional safe `permission` attribute)/`MetaRejected`/`MetaUnexpectedResponse`, and `InstagramGateway(client, clock)` with `exchange_code`, `exchange_long_lived`, `refresh`, `fetch_me`
- [X] T015 Create `backend/app/instagram_connections.py` skeleton: router `prefix="/api"`, dependencies (`get_instagram_credential_store`, `get_instagram_gateway`, `get_instagram_registry`), messages, `get_instagram_account_or_error` (404 / `platform_not_supported`), `get_connection`, `oauth_configured()`, `identity_of(connection)`, `connection_to_read(session, connection)` (marks `reconnect_required` locally when `credential_expires_at` has passed), `attempt_to_read`, `ensure_account_connectable`, `_store_unavailable()` and `RedactInstagramSecrets` + `install_log_redaction()` (redacts `access_token`, `client_secret`, `code`, `state` query values and `Bearer` values in `HTTP_LOGGERS`)
- [X] T016 Wire the composition root in `backend/app/main.py`: new `create_app` params `instagram_credential_store: CredentialStore | None` (default `KeyringCredentialStore(INSTAGRAM_SERVICE)`) and `instagram_transport: httpx.BaseTransport | None`; in `lifespan` create `app.state.instagram_credential_store`, `app.state.instagram_attempts = InstagramAttemptRegistry()` and an `httpx.Client` (10 s timeout) for `app.state.instagram_gateway`; call `instagram_connections.install_log_redaction()`; include `instagram_connections.router`; do **not** add any Instagram publisher
- [X] T017 Run `uv run pytest tests/test_instagram_oauth.py tests/test_instagram_gateway.py tests/test_migrations.py tests/test_accounts.py` and the full backend suite to confirm nothing existing broke

**Checkpoint**: modelo, migración, lógica pura, gateway y fakes listos.

---

## Phase 3: User Story 1 - Conectar una cuenta Instagram con una cuenta Professional real (Priority: P1) 🎯 MVP

**Goal**: `Not connected` → `Connect Instagram` → pegar dirección → `Connected` con identidad
Professional, token largo solo en el keyring.

**Independent Test**: con `FakeMeta`, autorizar, completar con la URL pegada y comprobar
`Connected` (username, tipo, ID, caducidad), secreto en el store en memoria, ninguna fila con
token, persistencia tras reiniciar la app; cuentas de otras plataformas rechazadas;
configuración ausente → `instagram_oauth_not_configured`.

### Tests for User Story 1

- [X] T018 [P] [US1] Write `backend/tests/test_instagram_connect.py`: `GET …/instagram-connection` returns `not_connected` with `oauth_configured`; `authorize` returns `attempt_id`, `authorization_url` (exact params) and `expires_at`; complete with Business and with Creator (`MEDIA_CREATOR`) → `completed`, connection read fields, `access_expires_at`; secret stored under the row's `credential_ref` contains only the long-lived token (short token never stored); requests to Meta in the documented order; restart (`create_app` again on the same DB and store) keeps `connected`; non-Instagram account → `409 platform_not_supported` for every route; missing/invalid config → `503 instagram_oauth_not_configured` and no attempt created; `oauth_configured` changes without restart
- [X] T019 [P] [US1] Write `frontend/src/components/InstagramConnectionPanel.test.tsx` (US1 part): `Not connected` shows `Connect Instagram`; clicking opens the authorization URL in a new tab and shows the paste field; submitting the pasted redirect URL calls `completeInstagramAttempt` with it in the body, clears the field (the URL is no longer in the component state or DOM) and shows the synchronous result: `Connected` with username, account type label (`Business`/`Creator`), Instagram account ID, profile picture when present (neutral placeholder on load error) and access expiry date; `oauth_configured: false` shows setup guidance and no connect action; panel not rendered for non-Instagram accounts (in `AccountList`)

### Implementation for User Story 1

- [X] T020 [US1] Implement `complete_connection(session, store, account, identity, token)` in `backend/app/instagram_connections.py` (store secret with new `credential_ref` → create/update row with identity, `status=connected`, `credential_expires_at`, timestamps → commit; on failure rollback and best-effort delete of the new secret; on success best-effort delete of the old secret)
- [X] T021 [US1] Implement `GET /api/accounts/{account_id}/instagram-connection` and `POST /api/accounts/{account_id}/instagram-connection/authorize` (active checks, config load, state, registry `create` with `current_identity`) in `backend/app/instagram_connections.py`
- [X] T022 [US1] Implement `POST /api/instagram/oauth/attempts/{attempt_id}/complete` (receives the pasted redirect URL in the body; returns the attempt result synchronously; no `GET` attempt route) happy path in `backend/app/instagram_connections.py`: load config, `parse_redirect_url`, registry `consume_state`, re-check account/project active, `exchange_code` → verify `REQUIRED_PERMISSIONS ⊆ permissions` → `exchange_long_lived` → `fetch_me` → Professional check → `complete_connection` → `finish(COMPLETED)` and return the attempt read
- [X] T023 [P] [US1] Add types `InstagramAccountType`, `INSTAGRAM_ACCOUNT_TYPE_LABELS`, `InstagramConnectionStatus`, `InstagramIdentity`, `InstagramConnection`, `InstagramOAuthAttemptStatus`, `InstagramOAuthAttempt`, `InstagramAuthorizeResult` to `frontend/src/types.ts` (with "keep in sync" comments)
- [X] T024 [P] [US1] Add `getInstagramConnection`, `authorizeInstagram`, `completeInstagramAttempt(attemptId, redirectUrl)` (redirect URL only in the POST body, never in the request URL) to `frontend/src/api.ts` and their counterparts to `frontend/src/test-fake-api.ts`
- [X] T025 [US1] Create `frontend/src/components/InstagramConnectionPanel.tsx` with the `Not connected` / `Connected` views, connect flow (open tab, fallback link, pasted redirect URL field, *Complete connection*, *Cancel*), discard the pasted URL right after sending it, identity summary and expiry; no browser storage
- [X] T026 [US1] Render `InstagramConnectionPanel` for `account.platform === "instagram"` in `frontend/src/components/AccountList.tsx`, mirroring the YouTube condition

**Checkpoint**: US1 funcional y demostrable con fakes.

---

## Phase 4: User Story 2 - Rechazar cuentas no compatibles y manejar errores de autorización (Priority: P1)

**Goal**: cada fallo produce un error estructurado claro, sin credenciales guardadas y sin
cambiar el estado previo.

**Independent Test**: con `FakeMeta`, recorrer denegación, `state` inválido/reutilizado/de
otra cuenta, intento caducado o tras reinicio, URL ajena, intercambio fallido, permisos
incompletos, cuenta no Professional, Meta caído y respuesta inesperada.

### Tests for User Story 2

- [X] T027 [P] [US2] Add error-path tests to `backend/tests/test_instagram_connect.py`: `error=access_denied` → `400 instagram_oauth_denied`; other `error` → `instagram_oauth_provider_error`; wrong `state` → `400 instagram_oauth_state_invalid` and the attempt stays `pending` (correct paste afterwards still works); reused redirect after completion → `instagram_oauth_state_invalid`; redirect whose `state` belongs to another account's attempt → `instagram_oauth_state_invalid`; superseded attempt (latest-attempt-wins) and expired attempt → `410 instagram_oauth_attempt_expired`; unknown attempt (simulated restart with a new app) → `410 instagram_oauth_attempt_expired`; pasted redirect URL with another host/path → `400 instagram_oauth_redirect_url_invalid` (attempt stays `pending`); code exchange or long-lived exchange rejected → `502 instagram_token_exchange_failed`; missing one permission → `422 instagram_permission_missing` naming it; missing `permissions` field → `502 instagram_unexpected_response`; personal/unknown `account_type` → `422 instagram_account_not_professional` whose message states that only Instagram Professional Business or Creator accounts are supported and that the account must be converted to Professional in Instagram before retrying; any other OAuth `error` (e.g. account not authorized as tester) → `instagram_oauth_provider_error` without raw Meta data; Meta unavailable → `503 instagram_unavailable`; `/me` without `user_id` → `502 instagram_unexpected_response`; in every case the store is empty, no row changes the attempt is `failed` where the contract says so, and no error message contains the code, the `state` or the pasted URL
- [X] T028 [P] [US2] Add error rendering tests to `frontend/src/components/InstagramConnectionPanel.test.tsx`: API error messages shown for denied, invalid state, expired attempt, not professional (asserting the "only Professional Business or Creator accounts; convert it in Instagram and try again" guidance) and permission missing; the panel returns to its previous state and allows a new attempt

### Implementation for User Story 2

- [X] T029 [US2] Add `AttemptFailure` handling to the complete route in `backend/app/instagram_connections.py`: map parse/registry/gateway outcomes to the contract codes and statuses, finish the attempt as `failed` (except validation, redirect-URL-invalid and state-mismatch cases that keep it `pending`), use the not-Professional message (Business or Creator only; convert the account in Instagram and retry), map other OAuth errors to `instagram_oauth_provider_error`, discard any obtained token without storing it, log only `account_id` and exception type
- [X] T030 [US2] Show structured errors and allow retry in `frontend/src/components/InstagramConnectionPanel.tsx`

**Checkpoint**: US1 + US2 robustos frente a errores.

---

## Phase 5: User Story 3 - Desconectar una cuenta Instagram (Priority: P1)

**Goal**: `Disconnect` borra primero el secreto, luego la fila; idempotente; conserva
`Account` y publicaciones.

**Independent Test**: conectar con fakes, desconectar y comprobar store vacío, sin fila,
`Account` y `Publication` intactas; store no disponible conserva la conexión.

### Tests for User Story 3

- [X] T031 [P] [US3] Write `backend/tests/test_instagram_disconnect.py`: disconnect `connected` and `reconnect_required` → `not_connected`, secret deleted before the row, account fields and publications unchanged; idempotent on `not_connected`; allowed with inactive account/project; store `delete` raising `CredentialStoreUnavailable` → `503 credential_store_unavailable`, row and secret reference kept; pending attempts of the account expire; no request to Meta is made
- [X] T032 [P] [US3] Add disconnect tests to `frontend/src/components/InstagramConnectionPanel.test.tsx`: confirm dialog, `Not connected` afterwards, manual revocation hint (Instagram → Website permissions → Apps and websites), error kept visible when the store is unavailable

### Implementation for User Story 3

- [X] T033 [US3] Implement `POST /api/accounts/{account_id}/instagram-connection/disconnect` in `backend/app/instagram_connections.py`
- [X] T034 [P] [US3] Add `disconnectInstagram` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T035 [US3] Add the `Disconnect` action, confirmation and revocation hint to `frontend/src/components/InstagramConnectionPanel.tsx`

**Checkpoint**: MVP P1 completo (US1–US3).

---

## Phase 6: User Story 4 - Mantener la credencial válida y verificar la conexión (Priority: P2)

**Goal**: ciclo de vida propio de Instagram (renovación ≥ 24 h, temporales vs definitivos) y
`Verify connection`.

**Independent Test**: con `FakeClock`/clock inyectado y `FakeMeta`, comprobar renovación
oportunista, no renovación < 24 h, temporal sin cambio de estado, rechazo definitivo (`MetaTokenInvalid`) → `reconnect_required`,
secreto ausente → `reconnect_required`, Verify con identidad correcta/cambiada/distinta.

### Tests for User Story 4

- [X] T036 [P] [US4] Write `backend/tests/test_instagram_tokens.py` for `get_valid_credentials`: token < 24 h old is returned without refresh; ≥ 24 h is refreshed, secret rewritten under the same `credential_ref`, `credential_expires_at` updated; transient refresh failure with a still-valid token returns the current token and keeps `connected`; transient failure with an expiring token → `503 instagram_unavailable` and still `connected`; definitive refresh rejection (`MetaTokenInvalid` from the gateway) → `409 instagram_reconnect_required` and `reconnect_required` with identity kept; permission withdrawn (`MetaPermissionDenied`) → same; these service tests use the semantic gateway classification (fake gateway responses), not error numbers; expired token (local check) → `reconnect_required` without network; missing or unreadable secret → `reconnect_required`; store unavailable → `503 credential_store_unavailable` without state change; concurrent calls refresh only once (per-account lock); `GET` marks an expired connection `reconnect_required` without calling Meta
- [X] T037 [P] [US4] Write `backend/tests/test_instagram_verify.py` (service tests on the semantic classification): verify OK updates `username`, `account_type`, `profile_picture_url`, `last_verified_at`; different `user_id` → `409 instagram_identity_mismatch`, `reconnect_required`, stored identity unchanged; no longer Professional → `409 instagram_account_not_professional` + `reconnect_required`; Meta reports a missing/withdrawn `instagram_business_basic` or `instagram_business_content_publish` (`MetaPermissionDenied`, with and without a safely known permission) → `409 instagram_reconnect_required`, `reconnect_required`, public identity kept, message says a required permission is missing or was withdrawn and names it when known; definitive token rejection (`MetaTokenInvalid`) → `409 instagram_reconnect_required`; transient → `503 instagram_unavailable` with no state change; `reconnect_required` connection → `409 instagram_reconnect_required` without calling Meta; `not_connected` → `409 instagram_not_connected`; inactive account or project → `409 account_inactive`/`project_inactive` without calling Meta or touching the store; error precedence of contracts/api.md (`verify`, steps 1–6) is respected, e.g. a `reconnect_required` connection on an inactive account → inactive error, a non-Instagram inactive account → `platform_not_supported`, and steps 1–5 never read the store nor call Meta; works without the Meta App config file
- [X] T038 [P] [US4] Add frontend tests to `frontend/src/components/InstagramConnectionPanel.test.tsx`: `Verify connection` updates the shown identity; `Reconnect required` view shows explanation, `Reconnect` and `Disconnect` and **no** `Verify connection`; the permission-withdrawn message is displayed; mismatch and transient errors displayed

### Implementation for User Story 4

- [X] T039 [US4] Implement `mark_reconnect_required` and `get_valid_credentials(session, store, gateway, account_id)` (clock taken from the gateway) with the data-model policy, reacting only to semantic gateway exceptions, (`REFRESH_MIN_AGE = 24h`, `EXPIRY_MARGIN = 5 min`, per-account lock) in `backend/app/instagram_connections.py`
- [X] T040 [US4] Implement `fetch_identity` and `verify_identity` (shared service for Feature 009; only `connected` with active account and project; checks identity, Professional type and required permissions — `MetaPermissionDenied` → `reconnect_required` + `409 instagram_reconnect_required` with the safe permission message, identity kept) and `POST /api/accounts/{account_id}/instagram-connection/verify` in `backend/app/instagram_connections.py`
- [X] T041 [P] [US4] Add `verifyInstagramConnection` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T042 [US4] Add `Verify connection` (only in `Connected`) and the `Reconnect required` view (without Verify) to `frontend/src/components/InstagramConnectionPanel.tsx`

**Checkpoint**: credenciales mantenidas y verificables.

---

## Phase 7: User Story 5 - Reconectar y proteger contra la cuenta Instagram equivocada (Priority: P2)

**Goal**: reconexión con la misma cuenta sustituye credenciales; otra cuenta exige
confirmación explícita; cancelar o caducar conserva la anterior.

**Independent Test**: con fakes, reconectar la misma identidad (secreto nuevo, antiguo
borrado), otra identidad (`awaiting_confirmation`, nada cambia), confirmar (identidad nueva,
secreto antiguo borrado) y cancelar/caducar (todo igual).

### Tests for User Story 5

- [X] T043 [P] [US5] Write `backend/tests/test_instagram_reconnect.py`: reconnect from `connected` and `reconnect_required` with the same `user_id` → `connected`, new `credential_ref`, old secret deleted, public data updated; different `user_id` → `awaiting_confirmation` with `current_identity`/`new_identity` (username and IDs), nothing stored; `confirm` → identity replaced, old secret deleted; `confirm` twice → `409 instagram_oauth_attempt_not_confirmable`; `cancel` → `cancelled`, pending token discarded, previous connection unchanged; expiry while awaiting → `expired`, unchanged; connection changed meanwhile → `409 instagram_connection_changed`; unknown attempt → `404 instagram_oauth_attempt_not_found`; account/project deactivated before confirm → `409`
- [X] T044 [P] [US5] Add frontend tests to `frontend/src/components/InstagramConnectionPanel.test.tsx`: `Reconnect` from `Connected` and `Reconnect required`; account-change warning shows current and new username and ID plus the affected AutoPublisher account; *Replace* calls confirm; *Cancel* calls cancel and keeps the previous identity

### Implementation for User Story 5

- [X] T045 [US5] Handle the different-identity branch in the complete route (`registry.await_confirmation`) and implement `POST /api/instagram/oauth/attempts/{attempt_id}/confirm` and `/cancel` in `backend/app/instagram_connections.py`
- [X] T046 [P] [US5] Add `confirmInstagramAttempt` and `cancelInstagramAttempt` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T047 [US5] Add `Reconnect` and the account-change confirmation UI to `frontend/src/components/InstagramConnectionPanel.tsx`

**Checkpoint**: nunca se cambia de cuenta sin confirmación.

---

## Phase 8: User Story 6 - Evitar la misma cuenta Instagram en dos Accounts del proyecto (Priority: P2)

**Goal**: unicidad por `(project_id, instagram_user_id)` respaldada por constraint.

**Independent Test**: dos `Account` del mismo proyecto con el mismo `user_id` → la segunda
falla; en otro proyecto se permite; tras desconectar se permite.

### Tests for User Story 6

- [X] T048 [P] [US6] Add uniqueness tests to `backend/tests/test_instagram_connect.py`: second account in the same project (active or inactive holder) → `409 instagram_account_already_connected` naming the holder's handle, nothing stored; another project → allowed; after disconnecting the holder → allowed; same username but different `user_id` → allowed; simulated race (rule check bypassed, `IntegrityError` from the constraint) → `409 instagram_account_already_connected` and the new secret deleted; the same rule applies on `confirm`

### Implementation for User Story 6

- [X] T049 [US6] Implement `ensure_identity_available(session, project_id, instagram_user_id, account_id)` and call it before `complete_connection` in complete and confirm; map `IntegrityError` in `complete_connection` to `instagram_account_already_connected` in `backend/app/instagram_connections.py`

**Checkpoint**: sin duplicados por proyecto.

---

## Phase 9: User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

**Goal**: estado visible, sin Connect/Reconnect ni completado con inactivos; Disconnect
permitido; desactivar no desconecta.

**Independent Test**: desactivar cuenta/proyecto y comprobar cada acción.

### Tests for User Story 7

- [X] T050 [P] [US7] Write `backend/tests/test_instagram_inactive.py`: `GET` works with inactive account/project; `authorize` → `409 account_inactive` / `project_inactive`; deactivation between authorize and complete → complete rejected, nothing stored, previous state kept; deactivating keeps the connection row and secret; `disconnect` allowed; `verify` → `409 account_inactive`/`project_inactive` without contacting Meta, refreshing or touching the store, also when the connection is `reconnect_required` or absent (inactive error takes precedence over `instagram_not_connected`/`instagram_reconnect_required`); with both inactive → `project_inactive`
- [X] T051 [P] [US7] Add frontend tests to `frontend/src/components/InstagramConnectionPanel.test.tsx`: with inactive account or project `Connect`/`Reconnect`/`Verify connection` are hidden or disabled with an explanation, `Disconnect` stays available

### Implementation for User Story 7

- [X] T052 [US7] Ensure the active checks in authorize/complete/confirm/verify of `backend/app/instagram_connections.py` cover all cases (verify checks before any gateway or store call; adjust if T050 fails)
- [X] T053 [US7] Apply the inactive rules (no Connect, Reconnect or Verify; Disconnect allowed) to actions in `frontend/src/components/InstagramConnectionPanel.tsx` (using `account.is_active` and `projectActive`)

**Checkpoint**: todas las historias completas.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T054 [P] Write `backend/tests/test_instagram_secrets.py`: after full flows (connect, refresh, verify, reconnect, confirm, failures) the SQLite file bytes and every table contain none of `FAKE_IG_CODE`, `FAKE_IG_SHORT_TOKEN`, `FAKE_IG_LONG_TOKEN`, `FAKE_IG_REFRESHED_TOKEN`, `FAKE_IG_APP_SECRET` or any issued `state`; JSON responses and error messages contain none of them, with the single exception of the `state` inside the `authorization_url` of `authorize` (no other secret there); captured logs at DEBUG for `HTTP_LOGGERS`, `uvicorn.access` and `app.*` contain none of them, nor `access_token=`/`client_secret=` with a value, nor `Bearer <token>`; `repr` of config, token and attempt objects hides secrets
- [X] T055 [P] Extend `frontend/src/storage-safety.test.tsx` with an Instagram flow (connect, paste, confirm) asserting nothing is written to `localStorage`/`sessionStorage` and the pasted redirect URL (with `code` and `state`) is discarded from the DOM and component state after submitting, including on errors
- [X] T056 [P] Create `docs/instagram-accounts.md`: Meta App (type Business), Instagram product with *API setup with Instagram login*, redirect URI registration and the pasted redirect URL flow (no HTTPS callback server), Instagram tester role and invitation (if the account is not a tester/role, Meta may fail on its own page or return an OAuth error shown as `instagram_oauth_provider_error`), converting a personal account to Professional (Business or Creator) for `instagram_account_not_professional`, local config file and `.gitignore`, Development Mode vs App Review/Advanced Access (research §15, stop rule), token lifetime and renewal (60 days, ≥ 24 h), manual revocation in Instagram, orphaned entries under service `autopublisher.instagram`, error codes and troubleshooting
- [X] T057 [P] Add a "Connecting Instagram" section to `README.md` (summary + link to `docs/instagram-accounts.md`) and update the "Status" paragraph that says other platforms only store an identity
- [X] T058 Run backend checks from `backend/`: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; fix any failure
- [X] T059 Run frontend checks from `frontend/`: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, `npm run build`; fix any failure
- [X] T060 Perform the manual validation of [quickstart.md](quickstart.md) section 2 with a real Professional account (checks A–D, stop rules) and record the results, including whether real renewal could be verified, in the PR description

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; **bloquea** todas las historias.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de US1 (ruta `complete`).
- **US3 (Phase 5)**: depende de Foundational; los tests usan el flujo de US1 para conectar.
- **US4 (Phase 6)**: depende de US1.
- **US5 (Phase 7)**: depende de US1 y US2 (manejo de intentos).
- **US6 (Phase 8)**: depende de US1; la regla en `confirm` depende de US5.
- **US7 (Phase 9)**: depende de US1, US3 y US5.
- **Polish (Phase 10)**: depende de todas las historias deseadas.

### Within Each User Story

- Tests primero (deben fallar) → backend → API cliente → componente.
- Las tareas de `backend/app/instagram_connections.py` son secuenciales entre sí (mismo
  archivo); igual para `InstagramConnectionPanel.tsx`.

### Parallel Opportunities

- Setup: T002 y T003.
- Foundational: T004–T009 (tests y fakes) en paralelo; luego T012, T013 y T014 en paralelo
  tras T010/T011.
- En cada historia, los tests backend y frontend marcados [P] en paralelo, y las tareas de
  `api.ts`/`types.ts` en paralelo con el backend.
- Polish: T054–T057 en paralelo.

---

## Parallel Example: Foundational

```text
T004 FakeMeta en backend/tests/fakes.py
T006 tests de instagram_oauth
T007 tests de instagram_gateway
T008 test de migración 0007
T009 test de arquitectura
# después de T010/T011:
T012 schemas · T013 instagram_oauth.py · T014 instagram_gateway.py
```

## Parallel Example: User Story 1

```text
T018 backend/tests/test_instagram_connect.py
T019 frontend/src/components/InstagramConnectionPanel.test.tsx
T023 frontend/src/types.ts
T024 frontend/src/api.ts + test-fake-api.ts
```

---

## Implementation Strategy

### MVP First (P1: US1 + US2 + US3)

1. Phase 1 + Phase 2.
2. US1 → validar con fakes (conectar y persistir).
3. US2 → errores robustos.
4. US3 → desconexión segura.
5. **Parar y validar**: quickstart §1 y, si se desea, §2 pasos 1–3 y 5.1 con una cuenta real
   (comprobaciones A–D antes de seguir).

### Incremental Delivery

1. MVP (US1–US3).
2. US4 (ciclo de vida + Verify).
3. US5 (reconexión con confirmación).
4. US6 (unicidad) — puede adelantarse tras US1 si se prefiere.
5. US7 (inactivos).
6. Polish: secretos, documentación, checks y validación real.

---

## Notes

- No se publica contenido ni se registra `InstagramPublisher` (Feature 009).
- No se modifica el código de YouTube; el registro de intentos de Instagram es propio.
- Commits pequeños en inglés solo cuando el usuario lo pida.
- Si la validación real falla en A (redirect URI), B (App Review) o D (`permissions`), se
  detiene y se revisa el plan antes de continuar.
