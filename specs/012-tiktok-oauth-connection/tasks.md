---

description: "Task list for the TikTok account connection (Login Kit for Desktop OAuth) feature"
---

# Tasks: Conexión de cuentas reales de TikTok mediante OAuth oficial (Login Kit for Desktop)

**Input**: Design documents from `specs/012-tiktok-oauth-connection/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-057, SC-010). Ningún test usa TikTok real,
Internet ni el keyring real: se usa `FakeTikTok` (`httpx.MockTransport`),
`InMemoryCredentialStore` y reloj falso; el fixture autouse `isolate_system_keyring` de
`backend/tests/conftest.py` sigue instalando un backend que falla. En cada historia los tests se
escriben primero y deben fallar antes de implementar.

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

- **Protocolo** (research §2–§8, §13; no inventar nada más):
  - autorización: `https://www.tiktok.com/v2/auth/authorize/` con `client_key`,
    `scope=user.info.basic,video.publish`, `response_type=code`, `redirect_uri`, `state`,
    `code_challenge`, `code_challenge_method=S256`; ningún otro parámetro;
  - PKCE: `code_verifier = secrets.token_urlsafe(48)` (64 caracteres);
    `code_challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()` (**hex**, no
    base64url); **no** reutilizar `generate_pkce_pair` de YouTube;
  - intercambio: `POST https://open.tiktokapis.com/v2/oauth/token/` form (`client_key`,
    `client_secret`, `code`, `grant_type=authorization_code`, `redirect_uri`, `code_verifier`),
    cabecera `Cache-Control: no-cache`; **un solo intento**;
  - renovación: mismo endpoint, form (`client_key`, `client_secret`,
    `grant_type=refresh_token`, `refresh_token`);
  - revocación: `POST https://open.tiktokapis.com/v2/oauth/revoke/` form (`client_key`,
    `client_secret`, `token=<access_token>`);
  - identidad: `GET https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url`
    con `Authorization: Bearer`;
  - ningún secreto (client secret, código, verifier, tokens) en query strings de peticiones
    salientes (FR-021).
- **Callback**: ruta `GET /api/tiktok/oauth/callback` (constante `TIKTOK_CALLBACK_PATH`, sin
  barra final; validado en G-6). Lee `request.query_params.multi_items()`; parámetros
  documentados `code`, `scopes`, `state`, `error`, `error_description`; duplicados →
  inválido; no documentados se ignoran sin registrarse. Solo peticiones de cliente loopback
  (`127.0.0.1`/`::1`). **Nunca** sirve contenido en su
  propia URL: responde siempre `303 See Other` a la ruta limpia
  `/api/tiktok/oauth/result?outcome=…` (enumerado cerrado `connected` | `confirm_required` |
  `cancelled` | `failed` | `invalid`; research §6.1), que sirve la página mínima desde un
  diccionario fijo, con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`, sin
  `code`, `state`, tokens ni texto de TikTok. La URL entrante del callback nunca se registra.
- **Scopes (FR-008, FR-009)**: la conexión exige `{"user.info.basic","video.publish"} ⊆`
  scopes de la **respuesta de tokens**; el `scopes` del callback no decide. Fuente de los scopes
  vigentes: último intercambio/renovación correcto (`scopes_source`); Verify **no** los
  presenta como comprobados en vivo; ninguna llamada de Content Posting / `creator_info`.
- **Identidad**: `open_id` del intercambio == `open_id` de `user/info`; nunca el nombre visible.
- **Secretos**: access/refresh tokens, código, `state` completo, `code_verifier`,
  `code_challenge` (fuera de la URL de autorización), client secret, cabeceras `Authorization`
  y URLs entrantes del callback **nunca** en SQLite, logs (incluido `uvicorn.access`),
  mensajes de excepción o error, respuestas JSON ni `localStorage`/`sessionStorage`. Solo el
  keyring (servicio `autopublisher.tiktok`), sin fallback. **Única excepción**: `state` y
  `code_challenge` dentro de `authorization_url`.
- **Fuente de verdad**: el JSON del secreto (data-model) es autoritativo; las fechas de
  SQLite son un espejo informativo reparable.
- **Política de renovación** (research §10): `REFRESH_MARGIN = 1 h`, `EXPIRY_MARGIN = 5 min`;
  caducidades derivadas solo de `expires_in`/`refresh_expires_in`; candado por cuenta
  compartido por renovación, Verify y Disconnect; **sin scheduler ni renovación periódica**.
- **Clasificación semántica**: solo `tiktok_gateway.py` interpreta códigos de error de TikTok
  (research §14); el servicio trabaja con `TikTokUnavailable`, `TikTokGrantInvalid`,
  `TikTokRejected`, `TikTokClientError`, `TikTokTokenInvalid`, `TikTokScopeMissing`,
  `TikTokUnexpectedResponse`. Los `log_id` de TikTok pueden registrarse.
- **Fallos temporales** (`TikTokUnavailable`) **nunca** cambian el estado de conexión.
- **Errores**: formato existente `{"error": {"code", "message", "fields"}}` con códigos y
  estados HTTP de [contracts/api.md](contracts/api.md); `tiktok_*` con
  `AppError(status, code, message)`; genéricos existentes para `not_found`,
  `platform_not_supported`, `project_inactive`, `account_inactive`,
  `credential_store_unavailable`.
- **Orden seguro (FR-033, FR-034)**: credencial nueva bajo `credential_ref` **nueva** →
  (fila + registro de la ref anterior en `tiktok_credential_orphans`) en una transacción →
  commit → borrar secreto viejo → borrar fila de huérfano. Commit fallido → borrar secreto
  nuevo; conexión anterior intacta.
- **Disconnect** (research §13): solo afirma revocación si TikTok la confirma; secreto ausente
  ≠ credencial inválida según TikTok ≠ almacén inaccesible.
- **Independencia**: `accounts.py`, `Account`, `AccountRead`, `publishing.py`,
  `publications.py`, `scheduler.py`, `automation.py` y todo el código de YouTube, Instagram y
  Threads **no se modifican** (salvo la constante en `credential_store.py` y el registro en
  `main.py`). Los módulos `tiktok_*` no importan módulos de otras plataformas ni viceversa.
- **Sin publicación**: ningún publisher de TikTok en `app.state.publishers` (test en T009).
- **Único proceso**: el backend local se ejecuta con un único proceso/worker; el candado de
  renovación en memoria solo garantiza exclusión dentro de él (sin infraestructura distribuida).

---

## Phase 0: Gate de viabilidad

- [X] T000 Gate G of `specs/012-tiktok-oauth-connection/quickstart.md` (G-1…G-7) passed on 2026-10-14 — evidence recorded in the Gate G results table; no code involved

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: protección del repositorio y configuración base.

- [X] T001 Add the secret pattern `tiktok-app*.json` under the "Secrets and credentials" section of `.gitignore`
- [X] T002 [P] Add to `backend/app/config.py` a section "TikTok Login Kit (see specs/012-tiktok-oauth-connection/research.md)": `TIKTOK_ATTEMPT_TTL = timedelta(minutes=10)`, `TIKTOK_ATTEMPT_RETENTION = timedelta(minutes=10)`, `TIKTOK_CALLBACK_PATH = "/api/tiktok/oauth/callback"`, `DEFAULT_TIKTOK_REDIRECT_URI = "http://127.0.0.1:8000" + TIKTOK_CALLBACK_PATH` and `get_tiktok_app_file()` (default `BACKEND_DIR / "data" / "tiktok-app.json"`, overridable with `AUTOPUBLISHER_TIKTOK_APP_FILE`)
- [X] T003 [P] Add `TIKTOK_SERVICE = "autopublisher.tiktok"` next to `THREADS_SERVICE` in `backend/app/credential_store.py` (no logic changes)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: persistencia, módulos puros, gateway, fakes y composición. Bloquea todas las
historias.

### Tests fundacionales (escribir primero)

- [X] T004 [P] Add `FakeTikTok` to `backend/tests/fakes.py`: an `httpx.MockTransport` serving `POST open.tiktokapis.com/v2/oauth/token/` (both `authorization_code` and `refresh_token` grants), `POST open.tiktokapis.com/v2/oauth/revoke/` and `GET open.tiktokapis.com/v2/user/info/`; it parses and records form bodies, verifies `code_verifier` against the challenge registered by the test (hex SHA-256) and rejects a mismatch with `invalid_grant`; configurable `open_id` per grant and for `user/info` (to simulate incoherence), `display_name`, `avatar_url`, returned `scope` strings, `expires_in`/`refresh_expires_in`, refresh-token rotation (new value or same value), revoke outcome (success with empty body, `{}`, `invalid_grant`, `access_token_invalid`, 5xx, timeout, unexpected body), per-endpoint faults (transport error, timeout, 5xx, 429, OAuth errors `invalid_grant`/`invalid_client`/`invalid_request`/`server_error`/`temporarily_unavailable`, error JSON returned with HTTP 200, API errors `access_token_invalid`/`scope_not_authorized`/`rate_limit_exceeded`, malformed JSON, missing fields, `token_type` other than Bearer), per-endpoint call counters, and constants `FAKE_TT_CODE`, `FAKE_TT_ACCESS_TOKEN`, `FAKE_TT_REFRESH_TOKEN`, `FAKE_TT_ROTATED_REFRESH_TOKEN`, `FAKE_TT_CLIENT_SECRET`, `FAKE_TT_OPEN_ID`; plus `tiktok_app_config_json(redirect_uri=None)`
- [X] T005 [P] Add to `backend/tests/conftest.py`: fixtures `tiktok_app_file` (writes config to `tmp_path`, sets `AUTOPUBLISHER_TIKTOK_APP_FILE`), `tiktok_credential_store` (`InMemoryCredentialStore`), `fake_tiktok`, `make_tiktok_app(...)`/`tiktok_client` (`create_app(..., tiktok_credential_store=..., tiktok_transport=fake_tiktok.transport(), clock=fake_clock.now)` and `TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))` so `scope["server"]` and the client are loopback); helpers `create_tiktok_account(...)`, `start_tiktok_authorization(...)` returning `(attempt_id, state, code_challenge)` parsed from `authorization_url`, `tiktok_callback(client, state, code=FAKE_TT_CODE, **extra)` and `poll_tiktok_attempt(...)`; make every existing `create_app` call in `conftest.py` also pass `tiktok_credential_store=InMemoryCredentialStore()`
- [X] T006 [P] Write `backend/tests/test_tiktok_oauth.py`: config loading (missing file, invalid JSON, empty `client_key`/`client_secret`; `redirect_uri` with a scheme other than `http`; host other than `127.0.0.1`/`localhost`; missing port; `*` port; path different from `TIKTOK_CALLBACK_PATH`, with trailing slash or common prefix; userinfo, query or fragment; ≥ 512 chars → `TikTokOAuthNotConfigured`; default redirect URI when absent; `client_secret` absent from `repr`); `generate_tiktok_pkce_pair` (verifier length 64 and charset ⊆ unreserved, new pair each call, challenge == lowercase 64-char hex of SHA-256 with a known test vector, explicitly **not** base64url); `build_authorization_url` exact params and order-independent equality (scope `user.info.basic,video.publish`, `code_challenge_method=S256`, no extra params); `parse_callback` (code only, code + `scopes`, `error=access_denied`, other `error` with `error_description`; rejects duplicated `code`/`state`/`error`/`scopes`/`error_description`, `code`+`error`, neither, empty or > 1024-char `code`; ignores undocumented params); `TikTokAttemptRegistry` (latest attempt wins, TTL expiry, unknown `state` returns `None`, `consume_state` moves to `processing` and returns the verifier exactly once, second consume returns `None`, verifier cleared afterwards, terminal retention and purge, `await_confirmation`/`claim_confirmation` once, `cancel` in `pending`/`awaiting_confirmation` and idempotent on `cancelled`, `cancel` rejected in `processing`, expiry or cancel of `awaiting_confirmation` invokes the injected discard callback with the pending credential and clears it, `expire_for_account`, `to_read()` never contains `state`, verifier or credentials)
- [X] T007 [P] Write `backend/tests/test_tiktok_gateway.py` against `FakeTikTok`: `exchange_code` sends a form POST with exactly the documented fields (no query string, `code_verifier` present) and builds a `TikTokCredential` with `obtained_at = clock()`, `access_expires_at = obtained_at + expires_in`, `refresh_expires_at = obtained_at + refresh_expires_in`, parsed scopes (comma split, trimmed) and `scopes_source="token_exchange"`; missing/ill-typed fields or `token_type` ≠ Bearer → `TikTokUnexpectedResponse`; error JSON with HTTP 200 treated as error; `refresh` form fields, always uses the returned `refresh_token` (rotated or not), `scopes_source="token_refresh"`, missing `refresh_token` → `TikTokUnexpectedResponse`; `revoke` form fields (`token` = access token) and success on empty body or `{}`; `fetch_user_info` query `fields=open_id,display_name,avatar_url`, Bearer header, requires `data.user.open_id` and `error.code == "ok"`, empty display name/avatar → `None`; classification table of research §14 tested **only here**; exception messages never contain tokens, codes, URLs or bodies and are raised `from None`; `TikTokCredential.to_json/from_json` round trip (version 1) and rejection of invalid stored JSON (missing fields, naive datetimes); `repr` hides both tokens
- [X] T008 [P] Add `test_migration_0011_creates_tiktok_tables` to `backend/tests/test_migrations.py`: tables `tiktok_connections` and `tiktok_credential_orphans` with the columns of data-model.md, CHECK on `status`, `UNIQUE(account_id)`, `UNIQUE(project_id, open_id)`, `UNIQUE(credential_ref)`, orphan PK `credential_ref`, upgrade/downgrade
- [X] T009 [P] Extend architecture tests: in `backend/tests/test_accounts.py` assert `accounts.py` imports nothing containing `tiktok` and `models.Account` has no `tiktok_connection` attribute; in `backend/tests/test_publications_states.py` add `test_core_modules_have_no_tiktok_code` (parametrized over `publishing`, `publications`, `scheduler`, `automation`: source contains no `tiktok_` and imports nothing starting with `app.tiktok`) and `test_no_tiktok_publisher_registered` (after `create_app` + startup, no key or publisher in `app.state.publishers` refers to `Platform.TIKTOK`; complements spec FR-006); add a test that `tiktok_oauth.py`, `tiktok_gateway.py`, `tiktok_connections.py` import nothing from `app.youtube`, `app.instagram` or `app.threads`, and that no module of those platforms imports `app.tiktok`

### Implementación fundacional

- [X] T010 Add `TikTokConnectionStatus` (`connected`, `reconnect_required`, "keep in sync with types.ts" docstring), `TikTokConnection` and `TikTokCredentialOrphan` (fields and constraints of data-model.md; no relationship on `Account`; comment that the date columns are an informational mirror of the secret) to `backend/app/models.py`
- [X] T011 Create migration `backend/migrations/versions/0011_create_tiktok_connections.py` (revises `0010`) with both tables, CHECK constraint, foreign keys (`RESTRICT`) and unique constraints of data-model.md, following the style of `0009_create_threads_connections.py`
- [X] T012 [P] Add `TikTokIdentityRead`, `TikTokPermissionsRead` (`granted`, `source`, `confirmed_at`), `TikTokConnectionRead` (fields of contracts/api.md), `TikTokAuthorizeRead`, `TikTokAttemptIdentityRead` (`display_name`, `avatar_url`, `open_id_suffix`), `TikTokOAuthAttemptRead` and `TikTokDisconnectRead` (`connection`, `revocation`: `revoked` | `already_invalid` | `not_revoked` | `not_connected`) to `backend/app/schemas.py`
- [X] T013 [P] Create `backend/app/tiktok_oauth.py`: `TIKTOK_AUTH_ENDPOINT`, `SCOPES`/`REQUIRED_SCOPES`, `parse_scopes`, `TikTokAppConfig` (secret `repr=False`), `TikTokOAuthNotConfigured`, `load_tiktok_app_config(path)` (research §3), `generate_state()`, `generate_tiktok_pkce_pair()` (research §4), `build_authorization_url(config, state, challenge)`, `CallbackInvalid` + `CallbackResult` + `parse_callback(items)` (research §6), `TikTokIdentity` (`to_read()`, `suffix`), `TikTokAttemptStatus` (incl. `processing`), `TikTokOAuthAttempt` (`to_read()` without secrets) and `TikTokAttemptRegistry(clock, discard)` (data-model; same interface as the YouTube registry, no import from it)
- [X] T014 [P] Create `backend/app/tiktok_gateway.py`: endpoint constants, `TIKTOK_TIMEOUT_SECONDS = 10`, `TikTokCredential` (data-model; `to_json`/`from_json`, `has_required_scopes`), exceptions of research §14 (`TikTokError` base; `TikTokScopeMissing` with optional safe `scope`; optional safe `log_id`), and `TikTokGateway(client, clock)` with `exchange_code(code, verifier, config)`, `refresh(credential, config)`, `revoke(access_token, config)`, `fetch_user_info(access_token)`
- [X] T015 Create `backend/app/tiktok_connections.py` skeleton: module docstring, router `prefix="/api"` tag `tiktok`, dependencies (`get_tiktok_credential_store`, `get_tiktok_gateway`, `get_tiktok_registry`), messages (docs hint `docs/tiktok-accounts.md`), `get_tiktok_account_or_error` (404 / `platform_not_supported`), `get_connection`, `oauth_configured()`, `load_config()`, `identity_of(connection)`, `attempt_to_read`, `ensure_account_connectable`, `mark_reconnect_required`, `_store_unavailable()`, `_read_credential(store, ref)` (None when missing or unreadable), `TikTokCallbackOutcome` (closed enum `connected`, `confirm_required`, `cancelled`, `failed`, `invalid`; research §6.1), `result_redirect(outcome)` (`303` to `/api/tiktok/oauth/result?outcome=…`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`), `render_result_page(outcome)` (title/message from a fixed dict, never from the query; unknown → `invalid`; no scripts; same headers), `discard_credential(gateway, credential, account_id)` (research §13: loads the TikTok config, calls `gateway.revoke` with the temporary credential, catches **every** exception including missing config, never changes the caller's outcome, logs only `account_id`, `revoked`/`failed` and TikTok `log_id`, never persists the credential), `RedactTikTokCallbackQuery` (uvicorn access log: any path starting with `TIKTOK_CALLBACK_PATH` followed by `?` or `/` becomes `TIKTOK_CALLBACK_PATH + "?[redacted]"`), `RedactTikTokSecrets` (values of `access_token`, `refresh_token`, `client_secret`, `code`, `code_verifier`, `code_challenge`, `state`, `token` in query strings and form bodies, `Bearer` values, and the query of `www.tiktok.com/v2/auth/authorize/` URLs, on the same `HTTP_LOGGERS` as Threads) and `install_log_redaction()`
- [X] T016 Wire the composition root in `backend/app/main.py`: new `create_app` params `tiktok_credential_store: CredentialStore | None` (default `KeyringCredentialStore(TIKTOK_SERVICE)`) and `tiktok_transport: httpx.BaseTransport | None`; in `lifespan` create `app.state.tiktok_credential_store`, a separate `httpx.Client(transport=tiktok_transport, timeout=TIKTOK_TIMEOUT_SECONDS)` for `app.state.tiktok_gateway = TikTokGateway(client, resolved_clock)` and `app.state.tiktok_attempts = TikTokAttemptRegistry(resolved_clock, discard=lambda credential, account_id: discard_credential(app.state.tiktok_gateway, credential, account_id))` so a cancelled or expired account change discards its pending credential best-effort; call `tiktok_connections.install_log_redaction()`; include `tiktok_connections.router`; do **not** add any TikTok publisher; keep the single-process assumption (no multi-worker support added)
- [X] T017 Run `uv run pytest tests/test_tiktok_oauth.py tests/test_tiktok_gateway.py tests/test_migrations.py tests/test_accounts.py tests/test_publications_states.py` and the full backend suite to confirm nothing existing broke

**Checkpoint**: modelo, migración, lógica pura, gateway, fakes y redacción listos.

---

## Phase 3: User Story 1 - Conectar una Account de TikTok con una cuenta real (Priority: P1) 🎯 MVP

**Goal**: `Not connected` → `Connect TikTok` → consentimiento → callback automático →
`Connected` con identidad verificada, ambos scopes y credencial solo en el keyring.

**Independent Test**: con `FakeTikTok`, autorizar, llamar al callback con el `state` y el
código, consultar el intento y comprobar `Connected` (nombre, avatar, caducidades, permisos),
secreto completo en el store en memoria, ninguna fila con tokens, persistencia tras reiniciar;
otras plataformas rechazadas; configuración ausente → `tiktok_oauth_not_configured`.

### Tests for User Story 1

- [X] T018 [P] [US1] Write `backend/tests/test_tiktok_connect.py` (happy path): `GET …/tiktok-connection` returns `not_connected` with `oauth_configured`; `authorize` returns `attempt_id`, `authorization_url` (exact params) and `expires_at`; the attempt is `pending`; the callback with `state` + `code` (+ `scopes`) returns **`303`** with `Location: /api/tiktok/oauth/result?outcome=connected` (no `code`, `state` or token in the `Location`; `Cache-Control: no-store`; `Referrer-Policy: no-referrer`); following it, `GET /api/tiktok/oauth/result?outcome=connected` returns 200 with the fixed success page (no OAuth value, no TikTok text); `outcome` unknown, missing, repeated or containing markup → `invalid` page that never reflects the query; the attempt becomes `completed` with the connection read (`open_id`, `display_name`, `avatar_url`, `access_expires_at`, `refresh_expires_at`, `permissions.granted` both scopes, `permissions.source="token_exchange"`); TikTok calls in order token exchange → `user/info`, the exchange exactly once and with the `code_verifier` whose hex challenge was in the authorization URL; the secret under the row's `credential_ref` has every field of data-model.md; SQLite date mirror equals the secret; restart (`create_app` again on same DB and store) keeps `connected`; non-TikTok account → `platform_not_supported` on every account route; missing/invalid config → `503 tiktok_oauth_not_configured` without creating an attempt; backend socket port different from the `redirect_uri` port (client with `base_url="http://127.0.0.1:8001"`) → `503 tiktok_oauth_not_configured`; `oauth_configured` changes without restart; Threads config present but TikTok config absent → still not configured; **interim fail-closed (until T050)**: account already linked to `oid-A` and callback returning `oid-B` → outcome `failed`, attempt `failed` with a safe code, no new secret stored, connection row/ref/secret unchanged, `discard_credential` invoked; same `oid-A` → completes normally; **uniqueness from the first flow**: another account of the same project already linked to the same `open_id` (inserted directly in the DB) → outcome `failed`, attempt `failed` `tiktok_account_already_connected`, no secret left in the store
- [X] T019 [P] [US1] Write `frontend/src/components/TikTokConnectionPanel.test.tsx` (US1 part): `Not connected` shows `Connect TikTok`; clicking opens a tab synchronously, calls `authorizeTikTok`, navigates the tab to `authorization_url` and shows `Connecting` with a reopen link and `Cancel`; polling `getTikTokAttempt` (fake timers, every 2 s) until `completed` shows `Connected` with display name, avatar (neutral placeholder on missing/error), local handle, access expiry, renewable-authorization expiry, last verified and the permissions text "according to TikTok's last authorization" (never "verified now"); `oauth_configured: false` shows setup guidance pointing to `docs/tiktok-accounts.md` and no connect action; the panel renders only for `platform === "tiktok"` in `AccountList`; nothing written to `localStorage`/`sessionStorage`

### Implementation for User Story 1

- [X] T020 [US1] Implement `register_orphan(session, credential_ref, account_id, now)` (adds a `TikTokCredentialOrphan` row to the current transaction, no commit) and `complete_connection(session, store, account, identity, credential, now)` in `backend/app/tiktok_connections.py` with the safe order (store secret under a **new** `credential_ref` → create/update row and, when replacing, `register_orphan(previous_ref)` in the same transaction → commit; on `IntegrityError` for `UNIQUE(project_id, open_id)` rollback, delete the new secret and raise `AppError(409, "tiktok_account_already_connected", …)` (generic message here; the holder-specific message and pre-check arrive in T055 without duplicating this translation); on **any** other commit failure rollback, best-effort delete of the new secret (if that fails, register it as an orphan in a separate commit, best-effort) and re-raise; after a successful commit, delete the old secret and its orphan row best-effort) and `connection_to_read(session, store, connection, now, include_permissions)` (basic `not_connected`/`connected`/`reconnect_required` mapping; refresh-expiry handling completed in US3)
- [X] T021 [US1] Implement `GET /api/accounts/{account_id}/tiktok-connection` and `POST /api/accounts/{account_id}/tiktok-connection/authorize` in `backend/app/tiktok_connections.py` (active checks, config load, socket-port check against `redirect_uri` using `request.scope["server"]`, state + PKCE pair, registry `create` with `current_identity`)
- [X] T022 [US1] Implement `GET /api/tiktok/oauth/callback`, `GET /api/tiktok/oauth/result` and `GET /api/tiktok/oauth/attempts/{attempt_id}` in `backend/app/tiktok_connections.py`: the callback checks the loopback client, runs `parse_callback`, `consume_state` (→ `processing`, verifier taken once), re-checks account/project active, `exchange_code` → required scopes on the **token response** → `fetch_user_info` (`open_id` must equal the exchange one) → identity rule → `complete_connection` (whose `tiktok_account_already_connected` is reported as attempt `failed`, outcome `failed`, credential discarded) → `finish(COMPLETED)`, and **always** answers with `result_redirect(outcome)` (never content at the callback URL); **identity rule until T050**: no linked identity → normal happy path; same `open_id` as the linked one → completes normally; **different `open_id` → fail closed**: nothing stored, existing connection untouched, attempt `failed` with a safe code and message telling the user to disconnect first, `discard_credential` called best-effort (T050 replaces this branch with the explicit confirmation flow); the result route renders `render_result_page(outcome)`; the attempt route returns `TikTokOAuthAttemptRead` or `404 tiktok_oauth_attempt_not_found`
- [X] T023 [P] [US1] Add types `TikTokConnectionStatus`, `TikTokIdentity`, `TikTokPermissions`, `TikTokConnection`, `TikTokOAuthAttemptStatus`, `TikTokAttemptIdentity`, `TikTokOAuthAttempt`, `TikTokAuthorizeResult`, `TikTokRevocation`, `TikTokDisconnectResult` to `frontend/src/types.ts` ("keep in sync" comments)
- [X] T024 [P] [US1] Add `getTikTokConnection`, `authorizeTikTok`, `getTikTokAttempt`, `cancelTikTokAttempt` to `frontend/src/api.ts` and their counterparts to `frontend/src/test-fake-api.ts`
- [X] T025 [US1] Create `frontend/src/components/TikTokConnectionPanel.tsx` (props `account`, `projectActive`, same shape as `YouTubeConnectionPanel`, without importing it): `Not connected`, `Connecting` (reopen link kept only in component memory while the attempt lasts, `Cancel`, polling every 2 s with cleanup on unmount) and `Connected` views with the permissions wording of FR-043/FR-053; no browser storage
- [X] T026 [US1] Render `TikTokConnectionPanel` for `account.platform === "tiktok"` in `frontend/src/components/AccountList.tsx`, mirroring the existing platform conditions

**Checkpoint**: US1 funcional y demostrable con fakes.

---

## Phase 4: User Story 2 - Manejar errores de autorización, PKCE y permisos parciales (Priority: P1)

**Goal**: cada fallo deja un intento con error seguro y una página limpia, sin credenciales
guardadas y sin cambiar el estado previo.

**Independent Test**: con `FakeTikTok`, recorrer denegación, error del proveedor, callback
inválido, `state` desconocido/reutilizado/sustituido/caducado/tras reinicio, callback
repetido, intercambio rechazado, scopes parciales, `open_id` incoherente, TikTok caído,
cancelación y cliente no loopback.

### Tests for User Story 2

- [X] T027 [P] [US2] Add error-path tests to `backend/tests/test_tiktok_connect.py` following the callback table of contracts/api.md (every callback response is a `303` to `/api/tiktok/oauth/result?outcome=…` with the listed outcome and a `Location` free of `code`, `state` and any TikTok text): non-loopback client (`client=("192.168.1.5", 1)`) → `invalid`, attempt untouched; missing/unknown `state`, `state` of a superseded or cancelled attempt, `state` after restart (new app, same DB) → `invalid`, no TikTok call, no change; expired attempt → `invalid`, attempt `expired`; duplicated documented param, `code`+`error`, neither, empty/oversized `code` → `failed`, attempt `failed` `tiktok_oauth_callback_invalid`, no TikTok call; `error=access_denied` → `cancelled`, attempt `failed` `tiktok_oauth_denied`; other `error` (with `error_description` containing a marker string) → `failed`, attempt `tiktok_oauth_provider_error`, and the marker appears nowhere (redirect, result page, attempt, logs); second callback with the same `state` after success or during `processing` → `invalid`, no second exchange; exchange `invalid_grant` (PKCE mismatch, used code, redirect mismatch) → attempt `tiktok_token_exchange_failed`, exchange called once; token scopes `user.info.basic` only or `video.publish` only (even if the callback `scopes` lists both) → attempt `tiktok_permission_missing` naming the missing scope, no secret stored, `discard_credential` called; `open_id` missing or different in `user/info` → attempt `tiktok_unexpected_response`, credential discarded; TikTok unavailable at exchange or `user/info` → attempt `tiktok_unavailable`; store unavailable → attempt `credential_store_unavailable`, credential discarded; **first connection with a failure injected in the SQLite commit after the secret was stored** → no row, new secret deleted, attempt `failed` `internal_error`, credential discarded; `discard_credential` failing (revoke error or missing config) never changes the outcome; `cancel` on `pending` → `cancelled` and a later callback with its `state` → `invalid`; in every case the store is empty, no row changes, and no response, redirect, page or log contains the code, `state`, verifier, tokens or the callback query
- [X] T028 [P] [US2] Add error rendering tests to `frontend/src/components/TikTokConnectionPanel.test.tsx`: messages for denied, provider error, callback invalid, permission missing (names the permission and suggests connecting again granting both), exchange failed, unavailable, expired and cancelled attempts; the panel returns to its previous state and allows a new attempt; `Cancel` calls `cancelTikTokAttempt` and stops polling

### Implementation for User Story 2

- [X] T029 [US2] Add `AttemptFailure` handling to the callback in `backend/app/tiktok_connections.py`: map parse/registry/gateway outcomes to the attempt codes and redirect outcomes of contracts/api.md, finish the attempt as `failed` with a safe message, call `discard_credential` for any credential already obtained (never stored), log only `account_id`, error code and TikTok `log_id`; unexpected exceptions → attempt `internal_error` and outcome `failed`; every path ends in `result_redirect(outcome)`
- [X] T030 [US2] Implement `POST /api/tiktok/oauth/attempts/{attempt_id}/cancel` in `backend/app/tiktok_connections.py` (contracts/api.md; allowed with inactive entities)
- [X] T031 [US2] Show structured errors, cancellation and retry in `frontend/src/components/TikTokConnectionPanel.tsx`

**Checkpoint**: US1 + US2 robustos frente a errores.

### Validación real V1 (quickstart, fase V1)

- [X] T032 [US2] With the user's Sandbox config in `backend/data/tiktok-app.json`, run steps **V-1…V-8** of `specs/012-tiktok-oauth-connection/quickstart.md` with the real TikTok Sandbox (no publishing) and record PASS/STOP in its "Resultados" section; on any STOP (hex challenge rejected, redirect rejected, incompatible token/user info shape, `video.publish` not granted) stop and revise spec/plan before continuing; adjust `FakeTikTok` and gateway contract tests to the real shapes observed

---

## Phase 5: User Story 3 - Mantener la credencial válida y verificar la conexión (Priority: P1)

**Goal**: renovación on-demand con rotación del refresh token, consistencia secreto/SQLite,
Verify con señales vivas y scopes conocidos, `Reconnect required` solo con evidencia
definitiva.

**Independent Test**: con `FakeTikTok`, `InMemoryCredentialStore` y reloj falso, los 15 casos de
plan.md "Tests obligatorios de renovación" y los de Verify.

### Tests for User Story 3

- [X] T033 [P] [US3] Write `backend/tests/test_tiktok_tokens.py` with the 15 mandatory cases of plan.md ("Tests obligatorios de renovación"), including rotated vs non-rotated refresh token (a second renewal sends the new token, never the old), secret renewed + SQLite commit failure → new credential returned, secret not restored, next access repairs the mirror without renewing and idempotently, `store.set` failing twice → `credential_store_unavailable` with the old secret intact, concurrent renewals → one TikTok call, `invalid_client` → no state change, and the `GET` repair/mark rules of data-model.md
- [X] T034 [P] [US3] Write `backend/tests/test_tiktok_verify.py`: success without renewal → live signals checked (`user/info` called, `open_id` matches), `last_verified_at` updated, `permissions.source` unchanged (`token_exchange`), no call to `/oauth/token/`; success with renewal (token inside `REFRESH_MARGIN`) → `permissions.source="token_refresh"`; renewal returning scopes without `video.publish` → `409 tiktok_reconnect_required` and `reconnect_required`; changed display name/avatar updated; different `open_id` in `user/info` → `409 tiktok_identity_mismatch` + `reconnect_required`, identity not replaced; `access_token_invalid` with a supposedly valid token → exactly one renewal + one retry (success keeps `connected`; renewal `invalid_grant` → `reconnect_required`); `scope_not_authorized` → `reconnect_required`; TikTok unavailable → `503 tiktok_unavailable`, still `connected`; missing secret → `reconnect_required`; store unavailable → `503 credential_store_unavailable`; config missing when renewal is needed → `503 tiktok_oauth_not_configured`, no state change; not connected → `409 tiktok_not_connected`; no request to any Content Posting endpoint ever
- [X] T035 [P] [US3] Add Verify and expiry tests to `frontend/src/components/TikTokConnectionPanel.test.tsx`: `Verify connection` updates last verified and shows the permissions source wording without claiming a live `video.publish` check; `Reconnect required` view shows a safe explanation, `Reconnect` and `Disconnect`, and no `Verify`

### Implementation for User Story 3

- [X] T036 [US3] Implement `get_valid_credentials(session, store, gateway, account_id)` in `backend/app/tiktok_connections.py` (research §10–§11): per-account lock, secret read and `_sync_metadata`, refresh-expiry check, `REFRESH_MARGIN`/`EXPIRY_MARGIN`, renewal with `open_id` and scopes validation, single `store.set` retry, mirror commit failure tolerated, classification into `reconnect_required` / temporary / no state change; plus `call_with_token(...)` (one renewal + one retry on `TikTokTokenInvalid`) and `mark_scope_not_authorized(session, account_id, scope)`
- [X] T037 [US3] Complete `connection_to_read` with the `GET` repair/mark rules of data-model.md and `permissions` read from the secret (only for the single-connection `GET`, silent `null` when unreadable) in `backend/app/tiktok_connections.py`
- [X] T038 [US3] Implement `verify_identity` and `POST /api/accounts/{account_id}/tiktok-connection/verify` plus `get_linked_identity` in `backend/app/tiktok_connections.py` (error precedence of contracts/api.md; never rewrites scopes without a renewal)
- [X] T039 [P] [US3] Add `verifyTikTokConnection` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T040 [US3] Add `Verify connection`, the `Reconnect required` view and the expiry/permissions wording to `frontend/src/components/TikTokConnectionPanel.tsx`

**Checkpoint**: credencial utilizable a largo plazo; servicios listos para la Feature 013.

---

## Phase 6: User Story 4 - Desconectar con revocación oficial (Priority: P2)

**Goal**: `Disconnect` revoca en TikTok y solo afirma lo confirmado; `remove-local` explícito;
`Account` y publicaciones intactas.

**Independent Test**: con `FakeTikTok`, desconectar con revocación correcta, credencial inválida
según TikTok, fallo temporal, secreto ausente y almacén inaccesible, y comprobar estado final,
store y mensaje.

### Tests for User Story 4

- [X] T041 [P] [US4] Write `backend/tests/test_tiktok_disconnect.py`: revoke success (empty body and `{}`) → `revocation: "revoked"`, secret deleted then row deleted, `Account` and its publications unchanged; refresh expired in the secret, renewal `invalid_grant`, or revoke `invalid_grant`/`access_token_invalid` → `already_invalid`, local data deleted, response never says `revoked`; revoke 5xx/timeout/429/`invalid_client`/unexpected body, renewal temporary failure, or missing config → `503 tiktok_revoke_failed`, nothing deleted; **secret missing** (store reachable) → `409 tiktok_credential_missing`, **no TikTok call**, nothing deleted; **store unavailable** → `503 credential_store_unavailable`, no TikTok call, nothing deleted (these three cases asserted explicitly and distinctly); access token inside `EXPIRY_MARGIN` → renewed (new credential persisted) before revoking; inactive account/project → disconnect allowed including that renewal; not connected → `revocation: "not_connected"`, idempotent; `remove-local` after `tiktok_revoke_failed` and after `tiktok_credential_missing` → secret (if any) and row deleted, `revocation: "not_revoked"`; `remove-local` with store unavailable → 503, nothing deleted; secret delete failure after `revoked` → `credential_store_unavailable`, row kept; concurrent disconnect and renewal serialized by the account lock
- [X] T042 [P] [US4] Add Disconnect tests to `frontend/src/components/TikTokConnectionPanel.test.tsx`: confirmation dialog; distinct messages for `revoked` and `already_invalid`; `tiktok_revoke_failed` shows `Retry` and `Remove locally without revoking`; `tiktok_credential_missing` shows the "remote access may still exist" explanation and `Remove locally without revoking`; local removal requires a second confirmation with the warning and the *Manage app permissions* hint and calls `removeTikTokLocally`; inactive accounts still offer `Disconnect`

### Implementation for User Story 4

- [X] T043 [US4] Implement `disconnect_tiktok` and `POST /api/accounts/{account_id}/tiktok-connection/disconnect` in `backend/app/tiktok_connections.py` (research §13; under the account lock; cleanup of pending orphans first)
- [X] T044 [US4] Implement `POST /api/accounts/{account_id}/tiktok-connection/remove-local` in `backend/app/tiktok_connections.py` (contracts/api.md; no TikTok call)
- [X] T045 [P] [US4] Add `disconnectTikTok` and `removeTikTokLocally` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T046 [US4] Add the Disconnect flow, revoke-failure and credential-missing states, and the two-step local removal to `frontend/src/components/TikTokConnectionPanel.tsx`

**Checkpoint**: desconexión honesta y segura.

---

## Phase 7: User Story 5 - Reconectar de forma segura y proteger contra la cuenta equivocada (Priority: P2)

**Goal**: Reconnect con `credential_ref` nueva y orden seguro; cambio de cuenta solo con
confirmación explícita; huérfanos registrados y limpiados.

**Independent Test**: con fakes, reconectar con la misma cuenta y con otra (confirmar,
cancelar, caducar); inyectar fallo de commit y de borrado del secreto viejo.

### Tests for User Story 5

- [X] T047 [P] [US5] Write `backend/tests/test_tiktok_reconnect.py`: same `open_id` from `connected` and from `reconnect_required` → new `credential_ref`, old secret deleted after commit, no orphan row left, `connected_at` updated; commit failure → new secret deleted, previous row/ref/secret intact, no orphan row; old-secret delete failure after commit → new connection valid and usable, orphan row present, old ref never read again; different `open_id` → `awaiting_confirmation` with `current_identity` and `new_identity` (display name, avatar, `open_id_suffix`), nothing changed; `confirm` → linked to the new identity with the same safe order; `confirm` twice → `409 tiktok_oauth_attempt_not_confirmable`; `cancel` or TTL expiry → pending credential discarded (never stored) and revoked best-effort, connection intact; connection changed since the warning → `409 tiktok_connection_changed`; uniqueness and inactive checks re-run on confirm
- [X] T048 [P] [US5] Write `backend/tests/test_tiktok_orphans.py`: `cleanup_orphans` deletes orphan secrets and rows idempotently, tolerates already-missing secrets, never deletes a ref used by a connection, keeps the row when the store is unavailable; runs at startup and at the start of callback completion, disconnect and remove-local
- [X] T049 [P] [US5] Add Reconnect tests to `frontend/src/components/TikTokConnectionPanel.test.tsx`: `Reconnect` from `Connected` and `Reconnect required`; the account-change warning shows both identities with `Replace` / `Cancel` and calls `confirmTikTokAttempt` / `cancelTikTokAttempt`

### Implementation for User Story 5

- [X] T050 [US5] Replace the interim fail-closed branch of T022 with the confirmation flow: a different `open_id` in the callback → `await_confirmation` and outcome `confirm_required`; implement `POST /api/tiktok/oauth/attempts/{attempt_id}/confirm` in `backend/app/tiktok_connections.py` (contracts/api.md), reusing `complete_connection` and `discard_credential`
- [X] T051 [US5] Implement `cleanup_orphans(session, store)` in `backend/app/tiktok_connections.py` (idempotent and opportunistic: deletes orphan secrets and their rows, tolerates already-missing secrets, never touches a ref in use, keeps the row when the store is unavailable; `register_orphan` already exists from T020), call it at the start of callback completion, disconnect and remove-local, and once from the `lifespan` startup in `backend/app/main.py` (best-effort, no secrets logged)
- [X] T052 [P] [US5] Add `confirmTikTokAttempt` to `frontend/src/api.ts` and `frontend/src/test-fake-api.ts`
- [X] T053 [US5] Add `Reconnect` and the account-change confirmation to `frontend/src/components/TikTokConnectionPanel.tsx`

**Checkpoint**: sustitución de credenciales crash-safe.

---

## Phase 8: User Story 6 - Evitar la misma cuenta TikTok en dos Accounts del proyecto (Priority: P2)

**Goal**: un `open_id` por proyecto, resistente a concurrencia; independiente de otras
plataformas.

**Independent Test**: conectar `oid-A`, intentar conectarlo en otra `Account` del mismo proyecto
(rechazo) y de otro proyecto (permitido).

### Tests for User Story 6

- [X] T054 [P] [US6] Add uniqueness tests to `backend/tests/test_tiktok_connect.py`: same `open_id` in another account of the same project (active or inactive holder) → `failed` `tiktok_account_already_connected` naming the holder handle, credential discarded and revoked best-effort; another project → allowed; after the holder disconnects → allowed; two concurrent completions (`IntegrityError` path) → at most one succeeds; YouTube/Instagram/Threads connections in the same project never affect TikTok uniqueness

### Implementation for User Story 6

- [X] T055 [US6] Implement `ensure_identity_available(session, project_id, open_id, account_id)` in `backend/app/tiktok_connections.py` (pre-check before storing anything, raising `tiktok_account_already_connected` with the holder's handle) and apply it in callback completion and confirm; enrich the message of the `IntegrityError` translation added in T020 with the holder when it can be read, without duplicating that translation

**Checkpoint**: integridad por proyecto.

---

## Phase 9: User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

**Goal**: con entidades inactivas solo estado, cancelar, Disconnect y remove-local.

**Independent Test**: desactivar cuenta o proyecto y forzar cada operación.

### Tests for User Story 7

- [X] T056 [P] [US7] Write `backend/tests/test_tiktok_inactive.py` following research §18: inactive account or project → `GET` works; `authorize`, `verify` and `confirm` → `409 account_inactive`/`project_inactive` without TikTok calls or store access; account deactivated after `authorize` → callback finishes `failed` without exchanging the code; deactivated while `awaiting_confirmation` → `confirm` rejected and pending credential discarded; `cancel`, `disconnect` (incl. renewal for revoke) and `remove-local` allowed; deactivating never deletes or revokes the connection
- [X] T057 [P] [US7] Add inactive tests to `frontend/src/components/TikTokConnectionPanel.test.tsx`: no `Connect`/`Reconnect`/`Verify` for inactive accounts or projects; status and `Disconnect` still shown

### Implementation for User Story 7

- [X] T058 [US7] Ensure every active operation in `backend/app/tiktok_connections.py` calls `ensure_account_connectable` before any store or TikTok access, and that the panel in `frontend/src/components/TikTokConnectionPanel.tsx` hides active actions for inactive entities

**Checkpoint**: todas las historias completas.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T059 [P] Write `backend/tests/test_tiktok_secrets.py`: after full flows (connect, refresh, verify, reconnect, disconnect, failures) the SQLite dump, captured logs (including `uvicorn.access` records of the callback with `code`/`state`, `httpx2`/`httpcore2` records), every JSON response, every callback page and every exception message contain none of `FAKE_TT_ACCESS_TOKEN`, `FAKE_TT_REFRESH_TOKEN`, `FAKE_TT_ROTATED_REFRESH_TOKEN`, `FAKE_TT_CODE`, `FAKE_TT_CLIENT_SECRET`, the `state`, the verifier or the challenge (except `state` and challenge inside `authorization_url`); callback access-log lines read `/api/tiktok/oauth/callback?[redacted]`; outgoing requests never carry secrets in the query string
- [X] T060 [P] Confirm `frontend/src/storage-safety.test.tsx` covers the new TikTok files (extend its file list only if it is not glob-based)
- [X] T061 [P] Create `docs/tiktok-accounts.md`: Gate G setup (Sandbox, Login Kit Desktop, redirect URI, Content Posting API + Direct Post only for `video.publish`, target user), *Basic information* using the real `docs/privacy-policy.md` and `docs/terms-of-service.md` and the repository URL, local `backend/data/tiktok-app.json`, port note, the **single-process assumption** (run one backend process/worker; the in-memory refresh lock only protects within that process; multiple workers are not supported), the clean result page after authorization, permissions shown according to the last token response, Disconnect outcomes and manual revocation via *Manage app permissions*, no publishing in this feature
- [X] T062 [P] Add a "Connecting TikTok" section to `README.md` and update the status paragraph (TikTok accounts can be connected; publishing arrives in Feature 013)
- [X] T063 Run all checks: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .` in `backend/`; `npm test`, `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build` in `frontend/`; fix any failure
- [X] T064 Run steps **V-9…V-19** of `specs/012-tiktok-oauth-connection/quickstart.md` with the real Sandbox (no publishing), record results, finish with the account `Connected` for Feature 013 (V-18) and the security review (V-19)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 0** (Gate G): done.
- **Setup (1)** → **Foundational (2)** → bloquea todas las historias.
- **US1 (3)** → **US2 (4)** (comparte el callback) → **V1 (T032)** antes de seguir.
- **US3 (5)** depende de US1 (conexión existente).
- **US4 (6)** depende de US3 (`get_valid_credentials` para renovar antes de revocar).
- **US5 (7)** depende de US1/US2 (callback) y reutiliza `complete_connection`.
- **US6 (8)** depende de US1; **US7 (9)** de todas las operaciones activas.
- **Polish (10)** al final.

### Within Each User Story

Tests primero (deben fallar) → backend → API frontend → componente → checkpoint.

### Parallel Opportunities

- Setup: T002, T003.
- Foundational tests: T004–T009 en paralelo; implementación T012–T014 en paralelo tras T010.
- Por historia: los tests backend y frontend `[P]` en paralelo; las funciones de `api.ts`
  `[P]` mientras se implementa el backend.
- Polish: T059–T062 en paralelo.
- Todas las tareas de backend sobre `tiktok_connections.py` son secuenciales entre sí.

## Parallel Example: Foundational

```text
T004 FakeTikTok (fakes.py)            T006 test_tiktok_oauth.py
T005 fixtures (conftest.py)           T007 test_tiktok_gateway.py
T008 migration test                   T009 architecture tests
→ then T010 → T011, and in parallel T012 (schemas), T013 (tiktok_oauth.py), T014 (tiktok_gateway.py)
```

## Parallel Example: User Story 1

```text
T018 backend connect tests    T019 panel tests    T023 types.ts    T024 api.ts
→ T020 → T021 → T022 (backend, sequential) and T025 → T026 (frontend)
```

## Parallel Example: User Story 3

```text
T033 test_tiktok_tokens.py    T034 test_tiktok_verify.py    T035 panel tests    T039 api.ts
→ T036 → T037 → T038 (backend) and T040 (frontend)
```

## Implementation Strategy

### MVP First (P1: US1 + US2 → V1 → US3)

1. Setup + Foundational.
2. US1 + US2 → **V1 con TikTok real** (T032). STOP si PKCE hex, redirect o forma de respuesta no
   coinciden.
3. US3 (renovación + Verify): sin ella la conexión caduca en ~24 h, así que forma parte del MVP.

### Incremental Delivery

4. US4 (Disconnect con revocación).
5. US5 (Reconnect + huérfanos) y US6 (unicidad).
6. US7 (inactivos).
7. Polish + V2 (T064), terminando con la cuenta `Connected` para la Feature 013.

## Notes

- `[P]` = archivos distintos, sin dependencias pendientes.
- Commits pequeños en inglés por tarea o grupo lógico, solo cuando el usuario lo pida.
- No publicar nada en TikTok en ninguna tarea.
- Detenerse en cada checkpoint para validar la historia de forma independiente.
