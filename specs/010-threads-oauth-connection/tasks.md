---

description: "Task list for the Threads account connection (official Threads API OAuth) feature"
---

# Tasks: Conexión de cuentas reales de Threads mediante OAuth oficial

**Input**: Design documents from `specs/010-threads-oauth-connection/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-053, SC-010). Ningún test usa Meta real,
Internet ni el keyring real: se usa `FakeThreads` (`httpx.MockTransport`) e
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

- **Protocolo** (research §2–§8; no inventar nada más):
  - autorización: `https://threads.com/oauth/authorize` con `client_id`, `redirect_uri`,
    `scope=threads_basic,threads_content_publish`, `response_type=code`, `state`; **sin PKCE**
    y sin ningún otro parámetro;
  - código → token corto: `POST https://graph.threads.net/oauth/access_token` (form:
    `client_id`, `client_secret`, `code`, `grant_type=authorization_code`, `redirect_uri`);
    respuesta `access_token`, `user_id`; **un solo intento, sin reintentos**;
  - corto → largo: `GET https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=…&access_token=…`
    → `access_token`, `expires_in`;
  - renovación: `GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=…`
    (sin app secret);
  - permisos: `GET https://graph.threads.net/v1.0/debug_token?input_token=<token largo>&access_token=<mismo token largo>`
    → `data.is_valid`, `data.user_id`, `data.scopes`, `data.data_access_expires_at`; **no** se usa
    App Access Token;
  - identidad: `GET https://graph.threads.net/v1.0/me?fields=id,username,name,threads_profile_picture_url&access_token=…`;
  - constantes únicas `THREADS_GRAPH_HOST = "https://graph.threads.net"`,
    `THREADS_API_VERSION = "v1.0"` (solo endpoints versionados) y
    `THREADS_AUTH_ENDPOINT = "https://threads.com/oauth/authorize"`.
- **Identidad**: `/me.id` es el Threads user ID autoritativo (`threads_user_id`) y debe
  coincidir con el `user_id` del intercambio y con `debug_token.user_id`; nunca el username.
- **Permisos (FR-008)**: la conexión solo se completa si `debug_token` devuelve
  `is_valid=true`, `user_id` coherente y `scopes` ⊇ {`threads_basic`,
  `threads_content_publish`}; en cualquier otro caso, fail-closed.
- **Redirect URL pegada (FR-014)**: parseo con `urlsplit` y comparación **exacta** de
  scheme, hostname, puerto efectivo y path con el `redirect_uri` configurado; sin
  `startswith`, sin tolerar barra final, sin userinfo; `code`/`state`/`error` solo desde la
  query y sin duplicados; fragment `#_` ignorado.
- **Secretos**: tokens (corto, largo, renovado), código, `state`, app secret, cabeceras
  `Authorization`, `input_token` y URLs con secretos **nunca** aparecen en SQLite, logs,
  mensajes de excepción o error, respuestas JSON ni `localStorage`/`sessionStorage`. Solo el
  token largo se guarda, solo en el keyring (servicio `autopublisher.threads`), sin fallback.
  **Única excepción** (FR-027): el `state` dentro de la `authorization_url` de `authorize`; la
  redirect URL pegada solo vive en la memoria del formulario y viaja en el cuerpo del POST de
  `complete`, y el frontend la descarta al enviarla.
- **Fuente de verdad**: el secreto (`access_token`, `token_obtained_at`, `expires_at`,
  `scopes`) es autoritativo; las columnas `token_obtained_at` y `credential_expires_at` de
  SQLite son un reflejo reparable (data-model).
- **`data_access_expires_at`**: solo informativo; último valor oficial de `debug_token`
  (conexión, Verify, inspección tras renovar); nunca se calcula sumando 90 días y **nunca**
  provoca por sí solo `reconnect_required`. Ese estado exige una señal oficial actual
  (`is_valid=false`, permiso ausente, 190/rechazo definitivo, mismatch), el token caducado según
  su propio `expires_at` o la credencial ausente.
- **Orden seguro (FR-029)**: cada conexión/reconexión/confirmación usa una `credential_ref`
  nueva; el secreto anterior solo se borra tras el commit correcto; un commit fallido borra el
  secreto nuevo y deja intacta la conexión anterior. Sin transacciones distribuidas genéricas.
- **Política de renovación** (data-model, FR-035): `RENEWAL_WINDOW = 7 días` es una constante
  interna de producto (no una regla de Meta); `REFRESH_MIN_AGE = 24 h` es la condición técnica
  de Meta; `EXPIRY_MARGIN = 5 min`. Solo se renueva dentro de `get_valid_credentials`; **sin
  scheduler ni renovación periódica**.
- **Clasificación semántica**: solo `threads_gateway.py` interpreta números de error de Meta;
  el servicio trabaja con `ThreadsUnavailable`, `ThreadsTokenInvalid`,
  `ThreadsPermissionDenied`, `ThreadsRejected` y `ThreadsUnexpectedResponse`. No existe el
  código público `threads_token_refresh_failed`.
- **Errores**: formato existente `{"error": {"code", "message", "fields"}}` con los códigos y
  estados HTTP de [contracts/api.md](contracts/api.md). Los `threads_*` se lanzan con
  `AppError(status, code, message)`; solo se reutilizan los genéricos existentes
  (`not_found`, `platform_not_supported`, `project_inactive`, `account_inactive`,
  `credential_store_unavailable`). Nunca datos crudos de Meta.
- **Fallos temporales** (`ThreadsUnavailable`) **nunca** cambian el estado de conexión.
- **Sin revocación remota** y sin callbacks de Meta (Deauthorize/Data Deletion): ningún código
  contacta con Meta al desconectar ni expone rutas para esos callbacks.
- **Independencia**: `backend/app/accounts.py`, `Account`, `AccountRead`, `publishing.py`,
  `publications.py`, `scheduler.py`, `automation.py` y todo el código de YouTube e Instagram
  **no se modifican** (salvo la constante en `credential_store.py` y el registro en
  `main.py`). Los módulos `threads_*` no importan `instagram_*` ni viceversa.
- **Sin publicación**: no se registra ningún publisher de Threads en `app.state.publishers`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: protección del repositorio y configuración base.

- [X] T001 Add the secret pattern `threads-app*.json` under the "Secrets and credentials" section of `.gitignore`
- [X] T002 [P] Add to `backend/app/config.py` (new section "Threads API (see specs/010-threads-oauth-connection/research.md)"): `THREADS_ATTEMPT_TTL = timedelta(minutes=10)`, `THREADS_ATTEMPT_RETENTION = timedelta(minutes=10)` and `get_threads_app_file()` (default `BACKEND_DIR / "data" / "threads-app.json"`, overridable with `AUTOPUBLISHER_THREADS_APP_FILE`)
- [X] T003 [P] Add `THREADS_SERVICE = "autopublisher.threads"` next to `INSTAGRAM_SERVICE` in `backend/app/credential_store.py` (no logic changes)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: persistencia, módulos puros, gateway, fakes y composición. Bloquea todas las
historias.

### Tests fundacionales (escribir primero)

- [X] T004 [P] Add `FakeThreads` to `backend/tests/fakes.py`: an `httpx.MockTransport` serving `POST graph.threads.net/oauth/access_token`, `GET graph.threads.net/access_token`, `GET graph.threads.net/refresh_access_token`, `GET graph.threads.net/v1.0/debug_token` and `GET graph.threads.net/v1.0/me`; configurable identity (`id`, `username`, `name`, `threads_profile_picture_url`), exchange `user_id` (to simulate incoherence), `debug_token` payload (`is_valid`, `user_id`, `scopes`, `data_access_expires_at`, missing fields), long-lived and refreshed `expires_in`, per-endpoint faults (transport error, 5xx, 429, Graph error codes 4/17/190/10/200/100, malformed JSON, missing fields), recorded requests with counters per endpoint, and constants `FAKE_TH_CODE`, `FAKE_TH_SHORT_TOKEN`, `FAKE_TH_LONG_TOKEN`, `FAKE_TH_REFRESHED_TOKEN`, `FAKE_TH_APP_SECRET`; plus a `threads_app_config_json(redirect_uri=...)` helper
- [X] T005 [P] Add to `backend/tests/conftest.py`: fixtures `threads_app_file` (writes the config to `tmp_path`, sets `AUTOPUBLISHER_THREADS_APP_FILE`), `threads_credential_store` (`InMemoryCredentialStore`), `fake_threads`, `make_threads_app(...)`/`threads_client` (`create_app(..., threads_credential_store=..., threads_transport=fake_threads.transport(), clock=fake_clock.now)`); helpers `create_threads_account(...)`, `start_threads_authorization(...)` returning `(attempt_id, state)` parsed from `authorization_url`, `threads_redirect_url_for(state, code=FAKE_TH_CODE)` (with `#_` suffix) and `complete_threads(...)`; make every existing `create_app` call in `conftest.py` also pass `threads_credential_store=InMemoryCredentialStore()`
- [X] T006 [P] Write `backend/tests/test_threads_oauth.py`: config loading (missing file, invalid JSON, non-numeric `app_id`, empty `app_secret`, `redirect_uri` non-https, without host, with userinfo, query or fragment → `ThreadsOAuthNotConfigured`; `app_secret` absent from `repr`); `build_authorization_url` exact params (scopes comma-separated, no `code_challenge`, no extra params); `parse_redirect_url` (success with `#_`, `error=access_denied`, other `error`; **rejects** unparseable URL, invalid port, different scheme, `localhost.evil.example`, `evil.example` with path `/localhost/...`, explicit `:8443` when configured without port, path with common prefix (`/callback-other`, `/callback/extra`), trailing slash not configured, userinfo `https://user@localhost/...`, duplicated `code`/`state`/`error`, neither `code` nor `error`; **accepts** explicit `:443` when configured without port and an upper-case scheme/host); `ThreadsAttemptRegistry` (latest-attempt-wins, TTL expiry, mismatched `state` does not consume, correct `state` consumed once, `secrets.compare_digest`, terminal retention and purge, `await_confirmation`/`claim_confirmation` once, `cancel` idempotent, `expire_for_account`, secrets cleared on finish)
- [X] T007 [P] Write `backend/tests/test_threads_gateway.py` against `FakeThreads`: code exchange is a form POST with the documented fields and returns `access_token` + `user_id` (int or string normalized to string); long-lived exchange params, `token_obtained_at = clock()` and `expires_at = token_obtained_at + expires_in`; missing/invalid `expires_in` → `ThreadsUnexpectedResponse`; refresh params (no app secret) and new timestamps; `debug_token` sends `input_token` = `access_token` = the given token on `/v1.0/debug_token`, parses `is_valid`, `user_id`, `scopes`, `data_access_expires_at` (0 or missing → `None`) and rejects missing/ill-typed fields with `ThreadsUnexpectedResponse`; `/me` uses `/v1.0/me` with the documented fields and requires `id` and `username`; error classification table of research §10 (transport/5xx/429/1/2/4/17/32/613 → `ThreadsUnavailable`, 190 → `ThreadsTokenInvalid`, 10/2xx → `ThreadsPermissionDenied` with the permission only when Meta names exactly one required scope, other 4xx → `ThreadsRejected`, bad JSON → `ThreadsUnexpectedResponse`) — numeric mappings tested only here; exception messages never contain tokens, URLs or bodies and are raised `from None`; `ThreadsToken.to_json/from_json` round trip and rejection of invalid stored JSON (missing fields, naive datetimes)
- [X] T008 [P] Add `test_migration_0009_creates_threads_connections` to `backend/tests/test_migrations.py`: table and columns of data-model.md, CHECK on `status`, `UNIQUE(account_id)`, `UNIQUE(project_id, threads_user_id)`, `UNIQUE(credential_ref)`, upgrade/downgrade
- [X] T009 [P] Extend architecture tests: in `backend/tests/test_accounts.py` assert `accounts.py` imports nothing containing `threads` and `models.Account` has no `threads_connection` attribute; in `backend/tests/test_publications_states.py` add `test_core_modules_have_no_threads_code` (parametrized over `publishing`, `publications`, `scheduler`, `automation`: source contains no `threads_` and imports nothing starting with `app.threads`); add a test that `threads_oauth.py`, `threads_gateway.py`, `threads_connections.py` import nothing from `app.instagram` and that no `app/instagram_*.py` module imports `app.threads`

### Implementación fundacional

- [X] T010 Add `ThreadsConnectionStatus` (`connected`, `reconnect_required`, "keep in sync with types.ts" docstring) and `ThreadsConnection` (fields of data-model.md including `token_obtained_at`, `credential_expires_at` with a comment stating it is exposed as `access_expires_at` in the API, nullable `data_access_expires_at` with a comment stating it is informational only, `display_name`; constraints; no relationship on `Account`) to `backend/app/models.py`
- [X] T011 Create migration `backend/migrations/versions/0009_create_threads_connections.py` (revises `0008`) with the columns, CHECK constraint, foreign keys (`RESTRICT`) and unique constraints of data-model.md, following the style of `0007_create_instagram_connections.py`
- [X] T012 [P] Add `ThreadsIdentityRead`, `ThreadsConnectionRead` (`status`, `identity`, `connected_at`, `last_verified_at`, `token_obtained_at`, `access_expires_at` documented as the API name of `ThreadsConnection.credential_expires_at`, `data_access_expires_at` documented as informational, `oauth_configured`), `ThreadsAuthorizeRead`, `ThreadsOAuthAttemptRead` and `ThreadsCompleteWrite` (`redirect_url`, max length 4096) to `backend/app/schemas.py`
- [X] T013 [P] Create `backend/app/threads_oauth.py`: `THREADS_AUTH_ENDPOINT`, `SCOPES`/`REQUIRED_SCOPES`, `ThreadsAppConfig` (secret with `repr=False`), `ThreadsOAuthNotConfigured`, `load_threads_app_config(path)`, `generate_state()`, `build_authorization_url(config, state)`, `InvalidRedirectUrl`, `RedirectResult` + `parse_redirect_url(pasted, config)` (research §4), `ThreadsIdentity` (`to_read()`), `ThreadsAttemptStatus`, `ThreadsOAuthAttempt` (`to_read()` without secrets) and `ThreadsAttemptRegistry` (research §14; same interface as the Instagram registry, no import from it)
- [X] T014 [P] Create `backend/app/threads_gateway.py`: host/version/endpoint constants, `ShortLivedToken`, `ThreadsToken` (`access_token` repr-hidden, `token_obtained_at`, `expires_at`, `scopes`, `to_json`/`from_json`), `ThreadsTokenInfo`, exceptions `ThreadsError`/`ThreadsUnavailable`/`ThreadsTokenInvalid`/`ThreadsPermissionDenied` (optional safe `permission`)/`ThreadsRejected`/`ThreadsUnexpectedResponse`, and `ThreadsGateway(client, clock)` with `exchange_code`, `exchange_long_lived`, `refresh`, `debug_token`, `fetch_me`
- [X] T015 Create `backend/app/threads_connections.py` skeleton: module docstring, router `prefix="/api"` tag `threads`, dependencies (`get_threads_credential_store`, `get_threads_gateway`, `get_threads_registry`), messages (docs hint `docs/threads-accounts.md`), `get_threads_account_or_error` (404 / `platform_not_supported`), `get_connection`, `oauth_configured()`, `load_config()`, `identity_of(connection)`, `attempt_to_read`, `ensure_account_connectable`, `mark_reconnect_required`, `_store_unavailable()`, and `RedactThreadsSecrets` + `install_log_redaction()` (redacts `access_token`, `input_token`, `client_secret`, `code`, `state` query values, `Bearer` values and `TH|…` values in the same `HTTP_LOGGERS` as Instagram)
- [X] T016 Wire the composition root in `backend/app/main.py`: new `create_app` params `threads_credential_store: CredentialStore | None` (default `KeyringCredentialStore(THREADS_SERVICE)`) and `threads_transport: httpx.BaseTransport | None`; in `lifespan` create `app.state.threads_credential_store`, `app.state.threads_attempts = ThreadsAttemptRegistry(resolved_clock)` and a separate `httpx.Client(transport=threads_transport, timeout=META_TIMEOUT_SECONDS)` for `app.state.threads_gateway = ThreadsGateway(client, resolved_clock)`; call `threads_connections.install_log_redaction()`; include `threads_connections.router`; do **not** add any Threads publisher
- [X] T017 Run `uv run pytest tests/test_threads_oauth.py tests/test_threads_gateway.py tests/test_migrations.py tests/test_accounts.py tests/test_publications_states.py` and the full backend suite to confirm nothing existing broke

**Checkpoint**: modelo, migración, lógica pura, gateway y fakes listos.

---

## Phase 3: User Story 1 - Conectar una Account de Threads con una cuenta real (Priority: P1) 🎯 MVP

**Goal**: `Not connected` → `Connect Threads` → pegar dirección → `Connected` con identidad
verificada, permisos confirmados y token largo solo en el keyring.

**Independent Test**: con `FakeThreads`, autorizar, completar con la URL pegada y comprobar
`Connected` (username, nombre, ID, caducidades), secreto en el store en memoria, ninguna fila
con token, persistencia tras reiniciar; otras plataformas rechazadas; configuración ausente →
`threads_oauth_not_configured`.

### Tests for User Story 1

- [X] T018 [P] [US1] Write `backend/tests/test_threads_connect.py` (happy path): `GET …/threads-connection` returns `not_connected` with `oauth_configured`; `authorize` returns `attempt_id`, `authorization_url` (exact params of research §5) and `expires_at`; complete → `completed` with connection read fields (`threads_user_id`, `username`, `display_name`, `profile_picture_url`, `token_obtained_at`, `access_expires_at`, `data_access_expires_at`); requests to Meta in order code exchange → long-lived → `debug_token` → `/me`, code exchange called exactly once; the secret under the row's `credential_ref` holds only the long-lived token with `token_obtained_at`, `expires_at` and `scopes` (short token never stored); SQLite `token_obtained_at`/`credential_expires_at` equal the secret's; restart (`create_app` again on same DB and store) keeps `connected`; non-Threads account → `409 platform_not_supported` on every route; missing/invalid config → `503 threads_oauth_not_configured` and no attempt created; `oauth_configured` changes without restart; Instagram config present but Threads config absent → still `threads_oauth_not_configured`
- [X] T019 [P] [US1] Write `frontend/src/components/ThreadsConnectionPanel.test.tsx` (US1 part): `Not connected` shows `Connect Threads`; clicking opens the authorization URL in a new tab and shows the paste field; submitting calls `completeThreadsAttempt` with the URL in the body, clears the field (URL no longer in state or DOM) and shows `Connected` with username, display name when present, Threads user ID, profile picture when present (neutral placeholder on load error), access expiry and data access expiry when present; `oauth_configured: false` shows setup guidance and no connect action; panel rendered only for `platform === "threads"` in `AccountList`

### Implementation for User Story 1

- [X] T020 [US1] Implement `complete_connection(session, store, account, identity, token, token_info, now)` in `backend/app/threads_connections.py` with the safe order of data-model (store secret under a **new** `credential_ref` → create/update row with identity, `status=connected`, `credential_ref`, `token_obtained_at`, `credential_expires_at`, `data_access_expires_at`, timestamps → commit; on **any** commit failure rollback, best-effort delete of the new secret and re-raise, leaving any previous row and its secret untouched (the route reports `500 internal_error`); only after a successful commit best-effort delete of the old secret, logging an orphan warning without secrets if that fails) and `connection_to_read(session, store, connection, now)` (basic version: `not_connected`/`connected`/`reconnect_required` mapping; expiry handling is completed in US4)
- [X] T021 [US1] Implement `GET /api/accounts/{account_id}/threads-connection` and `POST /api/accounts/{account_id}/threads-connection/authorize` (active checks, config load, state, registry `create` with `current_identity`) in `backend/app/threads_connections.py`
- [X] T022 [US1] Implement `_confirm_grant(gateway, access_token, expected_user_id) -> ThreadsTokenInfo` (`debug_token`; requires `is_valid`, matching `user_id` and both required scopes) and `POST /api/threads/oauth/attempts/{attempt_id}/complete` happy path in `backend/app/threads_connections.py`: load config, `parse_redirect_url`, registry `consume_state`, re-check account/project active, `exchange_code` → `exchange_long_lived` → `_confirm_grant` → `fetch_me` (`id` must equal exchange `user_id`) → `complete_connection` → `finish(COMPLETED)`; return the attempt read synchronously; no `GET` attempt route
- [X] T023 [P] [US1] Add types `ThreadsConnectionStatus`, `ThreadsIdentity`, `ThreadsConnection`, `ThreadsOAuthAttemptStatus`, `ThreadsOAuthAttempt`, `ThreadsAuthorizeResult` to `frontend/src/types.ts` ("keep in sync" comments)
- [X] T024 [P] [US1] Add `getThreadsConnection`, `authorizeThreads`, `completeThreadsAttempt(attemptId, redirectUrl)` (URL only in the POST body) to `frontend/src/api.ts` and their counterparts to `frontend/src/test-fake-api.ts`
- [X] T025 [US1] Create `frontend/src/components/ThreadsConnectionPanel.tsx` (props `account`, `projectActive`, same shape as `InstagramConnectionPanel`, without importing it) with the `Not connected` / `Connected` views, connect flow (open tab, fallback link, pasted redirect URL field, *Complete connection*, *Cancel*), discard of the pasted URL after sending, identity summary and expiry dates; no browser storage
- [X] T026 [US1] Render `ThreadsConnectionPanel` for `account.platform === "threads"` in `frontend/src/components/AccountList.tsx`, mirroring the existing platform conditions

**Checkpoint**: US1 funcional y demostrable con fakes.

---

## Phase 4: User Story 2 - Manejar errores de autorización y permisos insuficientes (Priority: P1)

**Goal**: cada fallo produce un error estructurado claro, sin credenciales guardadas y sin
cambiar el estado previo.

**Independent Test**: con `FakeThreads`, recorrer denegación, error del proveedor, URL
inválida, `state` inválido/reutilizado/caducado/de otra cuenta, intercambios fallidos,
permisos ausentes o no confirmables, `user_id` incoherente, Meta caído y respuesta inesperada.

### Tests for User Story 2

- [X] T027 [P] [US2] Add error-path tests to `backend/tests/test_threads_connect.py`: `error=access_denied` → `400 threads_oauth_denied`; other `error` → `400 threads_oauth_provider_error` without raw Meta data; every invalid redirect URL case of T006 through the route → `400 threads_oauth_redirect_url_invalid`, attempt stays `pending`, **no request to Meta**, and a correct paste afterwards completes; wrong `state` → `400 threads_oauth_state_invalid`, attempt stays `pending`; reused redirect after completion → `threads_oauth_state_invalid`; `state` of another account's attempt → `threads_oauth_state_invalid`; superseded, expired and unknown (restart) attempts → `410 threads_oauth_attempt_expired`; code exchange rejected (used/expired code) or long-lived exchange rejected → `502 threads_token_exchange_failed` with the code exchange called exactly once; `debug_token` with one scope missing → `422 threads_permission_missing` naming it; `is_valid=false` or permission error on `debug_token` → `422 threads_permission_missing`; `debug_token` without `scopes`/`is_valid` → `502 threads_unexpected_response`; `user_id` mismatch between exchange, `debug_token` and `/me` → `502 threads_unexpected_response`; Meta unavailable at any step → `503 threads_unavailable`; `/me` without `id` → `502 threads_unexpected_response`; store unavailable → `503 credential_store_unavailable`; **first connection with a generic failure injected in the SQLite commit after the new secret was stored** → no `threads_connections` row, the new secret is deleted from the store immediately (store empty), the account keeps `not_connected`, the attempt ends `failed` with `internal_error` and a safe message, and nothing sensitive is logged; in every case the store is empty, no row changes, the attempt is `failed` where the contract says so, and no message contains the code, `state`, tokens or the pasted URL
- [X] T028 [P] [US2] Add error rendering tests to `frontend/src/components/ThreadsConnectionPanel.test.tsx`: messages for denied, provider error, invalid redirect URL (field kept for correction), invalid state, expired attempt and permission missing; the panel returns to its previous state and allows a new attempt

### Implementation for User Story 2

- [X] T029 [US2] Add `AttemptFailure` handling to the complete route in `backend/app/threads_connections.py`: map parse/registry/gateway outcomes to the contract codes and statuses, finish the attempt as `failed` (except validation, redirect-URL-invalid and state-mismatch cases that keep it `pending`), map `ThreadsPermissionDenied`/`is_valid=false`/missing scopes to `threads_permission_missing`, discard any obtained token without storing it, log only `account_id` and the error code
- [X] T030 [US2] Show structured errors and allow retry in `frontend/src/components/ThreadsConnectionPanel.tsx`

**Checkpoint**: US1 + US2 robustos frente a errores.

---

## Phase 5: User Story 3 - Desconectar una cuenta Threads (Priority: P1)

**Goal**: `Disconnect` borra primero el secreto y luego la fila; idempotente; conserva
`Account` y publicaciones; solo local.

**Independent Test**: conectar con fakes, desconectar y comprobar store vacío, sin fila,
`Account` y `Publication` intactas; store no disponible conserva la conexión.

### Tests for User Story 3

- [X] T031 [P] [US3] Write `backend/tests/test_threads_disconnect.py`: disconnect `connected` and `reconnect_required` → `not_connected`, secret deleted before the row, account fields and publications unchanged; idempotent on `not_connected`; allowed with inactive account/project; store `delete` raising `CredentialStoreUnavailable` → `503 credential_store_unavailable`, row and reference kept; pending attempts of the account expire; `FakeThreads` records **no** request
- [X] T032 [P] [US3] Add disconnect tests to `frontend/src/components/ThreadsConnectionPanel.test.tsx`: confirm dialog, `Not connected` afterwards, manual revocation hint (Threads → Settings → Account → Website permissions), error kept visible when the store is unavailable

### Implementation for User Story 3

- [X] T033 [US3] Implement `POST /api/accounts/{account_id}/threads-connection/disconnect` in `backend/app/threads_connections.py` (no `ensure_not_publishing`: there is no Threads publishing yet)
- [X] T034 [P] [US3] Add `disconnectThreads` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T035 [US3] Add the `Disconnect` action, confirmation and revocation hint to `frontend/src/components/ThreadsConnectionPanel.tsx`

**Checkpoint**: MVP P1 completo (US1–US3).

---

## Phase 6: User Story 4 - Mantener la credencial válida y verificar la conexión (Priority: P2)

**Goal**: política de renovación de producto (ventana de 7 días + condición de 24 h de Meta),
consistencia secreto/SQLite y `Verify connection` de solo lectura.

**Independent Test**: con reloj falso y `FakeThreads`, los 12 escenarios de renovación y
consistencia de [plan.md](plan.md) y Verify con identidad correcta, cambiada, distinta y con
permiso retirado.

### Tests for User Story 4

- [X] T036 [P] [US4] Write `backend/tests/test_threads_tokens.py` for `get_valid_credentials` (scenarios 1–7 and 12 of plan.md): > 7 days left and ≥ 24 h old → returned without calling `refresh_access_token`; ≤ 7 days and ≥ 24 h → refreshed, secret rewritten under the same `credential_ref` with `token_obtained_at = now` and `expires_at = now + expires_in`, SQLite mirror updated; ≤ 7 days and < 24 h → returned without refresh while valid, and `reconnect_required` when also inside `EXPIRY_MARGIN` (AutoPublisher safety margin combined with Meta's 24 h condition, matching the research §6 table); transient refresh failure (transport, 5xx, 429, unexpected response) with a valid token → current token returned, `connected`, secret unchanged; transient failure inside `EXPIRY_MARGIN` → `503 threads_unavailable`, still `connected`; expired token → `reconnect_required` without network; 190 / permission denied / rejected refresh → `409 threads_reconnect_required`, identity kept; missing or unreadable secret → `reconnect_required`; store unavailable → `503 credential_store_unavailable` without state change; concurrent calls refresh once (per-account lock); `RENEWAL_WINDOW` is read from the module constant (test patches it to prove it is the only source of the window)
- [X] T037 [US4] After T036 (same file, sequential), add consistency tests to `backend/tests/test_threads_tokens.py` (scenarios 8–11 and 13–15 of plan.md): inject a failure in the SQLite commit after a successful refresh and `store.set` → the call returns the **new** token, the secret holds the new token (old one not restored), SQLite keeps the old metadata, status stays `connected`; next access reads the secret first, repairs `token_obtained_at` and `credential_expires_at` in SQLite and does **not** call `refresh_access_token` again; two further accesses leave the same metadata with no extra refresh (idempotent); a failure of the repair commit itself is logged and the token is still returned; `GET` with SQLite `credential_expires_at` in the past but a valid renewed secret → SQLite repaired, `connected`, no Meta call; same with the store unavailable → no state change, no error; with the secret also expired or missing → `reconnect_required`; **stale `data_access_expires_at`**: SQLite holds a past `data_access_expires_at` while the token is valid → `GET` stays `connected`; the token enters the window and is refreshed, the post-refresh `debug_token` returns `is_valid=true` and a future date → SQLite stores the official new date and the connection never becomes `reconnect_required` (asserted on `GET` before and after the refresh and on `get_valid_credentials`); no date is computed by adding 90 days; **post-refresh inspection with a transient failure** → new token returned and kept in the secret (old one not restored), previous `scopes` and `data_access_expires_at` kept, status `connected`; **post-refresh inspection with a definitive signal** (`is_valid=false`, missing scope, different `user_id`) → `reconnect_required`; **post-refresh scopes write failure**: refresh OK and new token stored, `debug_token` OK with scopes different from the stored ones, the `store.set` updating the scopes fails → the new token is returned and stays in the secret (old one not restored), status `connected` (no `reconnect_required`), SQLite `data_access_expires_at` still updated with the official value, a safe warning without secrets is logged, and the completed refresh is not invalidated (unlike Verify, where that write failing returns `credential_store_unavailable`)
- [X] T038 [P] [US4] Write `backend/tests/test_threads_verify.py`: verify OK calls `debug_token` and `/me`, updates `username`, `display_name`, `profile_picture_url`, `data_access_expires_at` and `last_verified_at`, and creates no content (only the five documented endpoints are ever requested); **secret during Verify**: unchanged confirmed scopes → no `store.set`; changed confirmed scopes → one `store.set` whose value keeps exactly the same `access_token`, `token_obtained_at` and `expires_at`; that `store.set` failing → `503 credential_store_unavailable`, previous secret intact, no Verify metadata committed (`last_verified_at` unchanged) and status still `connected`; a missing required scope → `reconnect_required` even when the store is unavailable (the transition does not depend on writing the secret); different `id` → `409 threads_identity_mismatch`, `reconnect_required`, identity unchanged; `debug_token` missing a required scope (with and without a safely known name) or `is_valid=false` → `409 threads_reconnect_required`, `reconnect_required`, identity kept, message names the scope when known; `ThreadsTokenInvalid` → `409 threads_reconnect_required`; transient → `503 threads_unavailable` without state change; `reconnect_required` → `409 threads_reconnect_required` without calling Meta; `not_connected` → `409 threads_not_connected`; error precedence of contracts/api.md (steps 1–5 never read the store nor call Meta); works without the Threads app config file
- [X] T039 [P] [US4] Add frontend tests to `frontend/src/components/ThreadsConnectionPanel.test.tsx`: `Verify connection` updates identity and dates; `Reconnect required` view shows explanation, `Reconnect` and `Disconnect` and **no** `Verify connection`; permission-withdrawn, mismatch and transient errors displayed

### Implementation for User Story 4

- [X] T040 [US4] Implement in `backend/app/threads_connections.py`: constants `RENEWAL_WINDOW = timedelta(days=7)` (comment: product decision, not a Meta rule), `REFRESH_MIN_AGE = timedelta(hours=24)` (comment: Meta's technical condition), `EXPIRY_MARGIN = timedelta(minutes=5)`; `_sync_metadata(session, connection, token)` (idempotent repair from the secret, logging a warning without secrets if its commit fails); `get_valid_credentials(session, store, gateway, account_id)` with the data-model policy (per-account lock, clock from the gateway, semantic exceptions only; on post-refresh SQLite commit failure: rollback, warning, continue with the new token, never restore the old one); post-refresh inspection (data-model step 8c) via `debug_token` on the new token: success → update secret `scopes` only if changed (keeping token and dates) and SQLite `data_access_expires_at` with the official value; definitive signal → `reconnect_required`; transient failure → keep the new token and last known metadata, warning without secrets; `data_access_expires_at` is never used to decide the state
- [X] T041 [US4] Complete `connection_to_read` in `backend/app/threads_connections.py`: never calls Meta; returns `data_access_expires_at` as is and **never** changes the state because of it; SQLite `credential_expires_at ≤ now` on a `connected` row → read the secret first (valid later expiry → `_sync_metadata` and stay `connected`; expired/missing → `reconnect_required`; store unavailable → unchanged)
- [X] T042 [US4] Implement `verify_identity` and `get_linked_identity` (services for Feature 011) and `POST /api/accounts/{account_id}/threads-connection/verify` in `backend/app/threads_connections.py` (precedence of contracts/api.md; `get_valid_credentials` → `_confirm_grant` → `fetch_me`; missing scope/`is_valid=false`/mismatch → `reconnect_required` without depending on any store write; rewrite the secret only when confirmed scopes changed, as a single `store.set` keeping `access_token`, `token_obtained_at` and `expires_at`; a failing write → `credential_store_unavailable` without committing Verify metadata or changing the state; then update public data, `data_access_expires_at` and `last_verified_at`)
- [X] T043 [P] [US4] Add `verifyThreadsConnection` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T044 [US4] Add `Verify connection` (only in `Connected`) and the `Reconnect required` view (without Verify) to `frontend/src/components/ThreadsConnectionPanel.tsx`

**Checkpoint**: credenciales mantenidas, coherentes y verificables.

---

## Phase 7: User Story 5 - Reconectar y proteger contra la cuenta Threads equivocada (Priority: P2)

**Goal**: reconexión con la misma cuenta sustituye credenciales; otra cuenta exige
confirmación explícita; cancelar o caducar conserva la anterior.

**Independent Test**: con fakes, reconectar la misma identidad (secreto nuevo, antiguo
borrado), otra identidad (`awaiting_confirmation`, nada cambia), confirmar y cancelar/caducar.

### Tests for User Story 5

- [X] T045 [P] [US5] Write `backend/tests/test_threads_reconnect.py`: reconnect from `connected` and `reconnect_required` with the same `id` → `connected`, new `credential_ref`, old secret deleted, public data and `token_obtained_at` updated; different `id` → `awaiting_confirmation` with `current_identity`/`new_identity`, nothing stored; `confirm` → identity replaced, old secret deleted; `confirm` twice → `409 threads_oauth_attempt_not_confirmable`; `cancel` → `cancelled`, pending token discarded, previous connection unchanged; expiry while awaiting → `expired`, unchanged; connection changed meanwhile → `409 threads_connection_changed`; unknown attempt → `404 threads_oauth_attempt_not_found`; account/project deactivated before confirm → `409`; **safe order on reconnect** (same identity) and on `confirm` (different identity) with a generic failure injected in the SQLite commit after the new secret was stored → the row still points to the previous `credential_ref`, the previous secret is still in the store and usable (`get_valid_credentials` returns the old token), the new secret is deleted, identity and status unchanged, and the route answers `500 internal_error` with a generic message (attempt `failed`, no internal details or secrets), matching contracts/api.md; **old secret deletion failing after a successful commit** → connection completed with the new reference, orphan warning logged without secrets
- [X] T046 [P] [US5] Add frontend tests to `frontend/src/components/ThreadsConnectionPanel.test.tsx`: `Reconnect` from `Connected` and `Reconnect required`; account-change warning shows current and new username and ID plus the affected AutoPublisher account; *Replace* calls confirm; *Cancel* calls cancel and keeps the previous identity

### Implementation for User Story 5

- [X] T047 [US5] Handle the different-identity branch in the complete route (`registry.await_confirmation` with token and token info) and implement `POST /api/threads/oauth/attempts/{attempt_id}/confirm` and `/cancel` in `backend/app/threads_connections.py`
- [X] T048 [P] [US5] Add `confirmThreadsAttempt` and `cancelThreadsAttempt` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T049 [US5] Add `Reconnect` and the account-change confirmation UI to `frontend/src/components/ThreadsConnectionPanel.tsx`

**Checkpoint**: nunca se cambia de cuenta sin confirmación.

---

## Phase 8: User Story 6 - Evitar la misma cuenta Threads en dos Accounts del proyecto (Priority: P2)

**Goal**: unicidad por `(project_id, threads_user_id)` respaldada por constraint.

**Independent Test**: dos `Account` del mismo proyecto con el mismo ID → la segunda falla; en
otro proyecto se permite; tras desconectar se permite.

### Tests for User Story 6

- [X] T050 [P] [US6] Add uniqueness tests to `backend/tests/test_threads_connect.py`: second account in the same project (active or inactive holder) → `409 threads_account_already_connected` naming the holder's handle, nothing stored; another project → allowed; after disconnecting the holder → allowed; same username but different `id` → allowed; simulated race (rule check bypassed, `IntegrityError`) → `409 threads_account_already_connected` and the new secret deleted; same rule on `confirm`; an Instagram connection in the same project never blocks a Threads connection

### Implementation for User Story 6

- [X] T051 [US6] Implement `ensure_identity_available(session, project_id, threads_user_id, account_id)`, call it before `complete_connection` in complete and confirm, and map `IntegrityError` in `complete_connection` to `threads_account_already_connected` in `backend/app/threads_connections.py`

**Checkpoint**: sin duplicados por proyecto.

---

## Phase 9: User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

**Goal**: estado visible, sin Connect/Reconnect/Verify ni completado con inactivos;
Disconnect y cancelar permitidos; desactivar no desconecta.

**Independent Test**: desactivar cuenta/proyecto y comprobar cada acción.

### Tests for User Story 7

- [X] T052 [P] [US7] Write `backend/tests/test_threads_inactive.py`: `GET` works with inactive account/project; `authorize` → `409 account_inactive`/`project_inactive`; deactivation between authorize and complete → complete rejected before any Meta request, nothing stored; deactivation before confirm → rejected; `cancel` allowed; deactivating keeps the connection row and secret; `disconnect` allowed; `verify` → inactive error without contacting Meta or touching the store, also when the connection is `reconnect_required` or absent; both inactive → `project_inactive`
- [X] T053 [P] [US7] Add frontend tests to `frontend/src/components/ThreadsConnectionPanel.test.tsx`: with inactive account or project `Connect`/`Reconnect`/`Verify connection` hidden or disabled with an explanation, `Disconnect` available

### Implementation for User Story 7

- [X] T054 [US7] Ensure the active checks in authorize/complete/confirm/verify of `backend/app/threads_connections.py` cover all cases (before any gateway or store call; adjust if T052 fails)
- [X] T055 [US7] Apply the inactive rules to actions in `frontend/src/components/ThreadsConnectionPanel.tsx` (using `account.is_active` and `projectActive`)

**Checkpoint**: todas las historias completas.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T056 [P] Write `backend/tests/test_threads_secrets.py`: after full flows (connect, refresh, repair, verify, reconnect, confirm, failures) the SQLite file bytes and every table contain none of `FAKE_TH_CODE`, `FAKE_TH_SHORT_TOKEN`, `FAKE_TH_LONG_TOKEN`, `FAKE_TH_REFRESHED_TOKEN`, `FAKE_TH_APP_SECRET`, any issued `state` or scopes; JSON responses and error messages contain none of them except the `state` inside `authorize`'s `authorization_url`; captured DEBUG logs of `HTTP_LOGGERS`, `uvicorn.access` and `app.*` contain none of them nor `access_token=`/`input_token=`/`client_secret=`/`code=`/`state=` with a value, `Bearer <token>` or `TH|`; `repr` of config, tokens, token info and attempts hides secrets
- [X] T057 [P] Extend `frontend/src/storage-safety.test.tsx` with a Threads flow (connect, paste, confirm, error) asserting nothing is written to `localStorage`/`sessionStorage` and the pasted redirect URL is discarded from DOM and state after submitting, including on errors
- [X] T058 [P] Create `docs/threads-accounts.md` (also recording, for Feature 011, the findings of research §9: `threads_content_publish` required, media must be publicly reachable at request time, publishing limit to be handled in 011, no profile-type requirement found; and that `data_access_expires_at` is informational): Meta App with the *Access the Threads API* use case, Threads App ID/Secret, Threads Tester role and invitation, redirect URI and the pasted redirect URL flow (no HTTPS callback server; strict validation), Deauthorize/Data Deletion URLs (not implemented by AutoPublisher; attempt without them; stop if Meta requires public functional URLs; no fictitious values or tunnels), local config file and `.gitignore`, permission check via `debug_token` and its tester limitation, token lifetime (60 days), renewal policy (7-day product window, 24 h Meta condition, no background refresh), grant expiry (90 days, private profiles), manual revocation in Threads, orphaned keyring entries under `autopublisher.threads`, error codes and troubleshooting
- [X] T059 [P] Add a "Connecting Threads" section to `README.md` (summary + link to `docs/threads-accounts.md`) and update the status paragraph listing connectable platforms
- [X] T060 Run backend checks from `backend/`: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; fix any failure
- [X] T061 Run frontend checks from `frontend/`: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, `npm run build`; fix any failure
- [X] T062 Perform the manual validation of [quickstart.md](quickstart.md) section 2 with a real Threads account (checks A–J2, stop rules A, B and F) without publishing anything; measure the time from submitting the redirect URL to `Connected` and record whether it meets SC-002 (< 10 s under normal network conditions, as a metric, not a functional timeout); delete any temporary `debug_token` script and never print the full keyring value or raw Meta responses; record the results in `quickstart.md` and the PR description

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; **bloquea** todas las historias.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de US1 (ruta `complete`).
- **US3 (Phase 5)**: depende de Foundational; sus tests usan el flujo de US1 para conectar.
- **US4 (Phase 6)**: depende de US1 (`complete_connection`, `_confirm_grant`, `connection_to_read`).
- **US5 (Phase 7)**: depende de US1 y US2.
- **US6 (Phase 8)**: depende de US1; la regla en `confirm` depende de US5.
- **US7 (Phase 9)**: depende de US1, US3, US4 y US5.
- **Polish (Phase 10)**: depende de todas las historias.

### Within Each User Story

- Tests primero (deben fallar) → backend → API cliente → componente.
- Las tareas de `backend/app/threads_connections.py` son secuenciales entre sí (mismo
  archivo); igual para `ThreadsConnectionPanel.tsx`, `test_threads_connect.py` y
  `test_threads_tokens.py`.

### Parallel Opportunities

- Setup: T002 y T003.
- Foundational: T004–T009 en paralelo; tras T010/T011, T012, T013 y T014 en paralelo.
- En cada historia, los tests backend y frontend [P] en paralelo, y `types.ts`/`api.ts` en
  paralelo con el backend.
- US4: T036 → T037 en orden (mismo archivo; T037 no es [P]); ese bloque en paralelo con T038
  y T039.
- Polish: T056–T059 en paralelo.

---

## Parallel Example: Foundational

```text
T004 FakeThreads en backend/tests/fakes.py
T006 tests de threads_oauth (validación estricta de redirect URL)
T007 tests de threads_gateway (debug_token, clasificación)
T008 test de migración 0009
T009 tests de arquitectura
# después de T010/T011:
T012 schemas · T013 threads_oauth.py · T014 threads_gateway.py
```

## Parallel Example: User Story 1

```text
T018 backend/tests/test_threads_connect.py
T019 frontend/src/components/ThreadsConnectionPanel.test.tsx
T023 frontend/src/types.ts
T024 frontend/src/api.ts + test-fake-api.ts
```

## Parallel Example: User Story 4

```text
T036 → T037 backend/tests/test_threads_tokens.py (secuenciales; T037 sin [P])
T038 backend/tests/test_threads_verify.py
T039 frontend/src/components/ThreadsConnectionPanel.test.tsx
T043 frontend/src/api.ts + test-fake-api.ts
```

---

## Implementation Strategy

### MVP First (P1: US1 + US2 + US3)

1. Phase 1 + Phase 2.
2. US1 → conectar y persistir con fakes.
3. US2 → errores robustos y validación estricta de la URL.
4. US3 → desconexión segura.
5. **Parar y validar**: quickstart §1 y, si se desea, §2 pasos 1–6 con la cuenta real
   (comprobaciones A, B y F bloqueantes antes de seguir).

### Incremental Delivery

1. MVP (US1–US3).
2. US4 (renovación, consistencia y Verify).
3. US5 (reconexión con confirmación).
4. US6 (unicidad) — puede adelantarse tras US1.
5. US7 (inactivos).
6. Polish: secretos, documentación, checks y validación real.

---

## Notes

- No se publica contenido ni se registra un publisher de Threads (Feature 011).
- No se modifica el código de YouTube ni de Instagram; el registro de intentos de Threads es
  propio (candidato a refactor futuro).
- Commits pequeños en inglés solo cuando el usuario lo pida.
- Si la validación real falla en A (redirect URI), B (callbacks de Meta) o F (`debug_token`),
  se detiene y se revisa el plan antes de continuar.
