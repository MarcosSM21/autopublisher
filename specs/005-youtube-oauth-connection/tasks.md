---

description: "Task list for the secure YouTube account connection (OAuth 2.0) feature"
---

# Tasks: Conexión segura de cuentas de YouTube mediante OAuth 2.0

**Input**: Design documents from `specs/005-youtube-oauth-connection/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-041, SC-009 y la lista de tests de la
petición original). Deben cubrir:

- conexión: iniciar, rechazo de cuenta no YouTube, `state` válido e inválido, callback
  exitoso y canal identificado;
- seguridad: referencia sin tokens en SQLite;
- ciclo de vida: persistencia tras reinicio, desconexión, reconexión, refresh exitoso y
  refresh inválido → `reconnect_required`;
- reglas de canal: conflicto de canal ya conectado y protección ante sustitución;
- estados y configuración: proyecto o cuenta inactivos y configuración ausente;
- frontend: estados Connect / Connected / Reconnect required.

Ningún test usa Google real, Internet ni el llavero real del sistema. En cada historia los
tests se escriben primero y deben fallar antes de implementar.

**Organization**: tareas agrupadas por historia de usuario (US1–US7 de la spec). Todo el
código, los comentarios, los mensajes de API, UI y HTML, el README y los commits van en
inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes).
- **[Story]**: historia de usuario a la que pertenece (US1–US7).

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`.
- Frontend: `frontend/src/`, `frontend/src/components/`.
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- **Secretos**: access token, refresh token, código de autorización, `code_verifier` y
  client secret **nunca** aparecen en:
  - SQLite;
  - logs, ni siquiera en los mensajes de las excepciones;
  - respuestas JSON;
  - el HTML del callback;
  - URLs de peticiones salientes;
  - `localStorage`.

  Los tokens viajan en el cuerpo del formulario o en la cabecera `Authorization`.
- **Almacén seguro**: `KeyringCredentialStore` comprueba la lista blanca de backends
  (research §8) **antes de cada** `set`, `get` y `delete`. Si no hay un backend seguro, o
  está bloqueado o falla, lanza `CredentialStoreUnavailable` →
  `503 credential_store_unavailable`. **Nunca** hay alternativa en archivo plano, SQLite ni
  memoria en producción.
- **Sin revocación**: ningún código llama al endpoint de revocación de Google. `Disconnect`
  y el descarte de credenciales son siempre locales (research §13).
- **Autorización**: toda URL de autorización lleva `access_type=offline`,
  `prompt=select_account consent`, `state`, `code_challenge` y
  `code_challenge_method=S256`, y exactamente los scopes `youtube.readonly` y
  `youtube.upload` (research §3–§5). Sin `refresh_token` en la respuesta, la conexión no se
  completa.
- **Canal efectivo**: solo se acepta si `channels.list?mine=true` devuelve exactamente
  1 canal. Con 0 → `youtube_no_channel`; con más de 1 → `youtube_channel_ambiguous`. Nunca se
  elige el primero.
- **Errores**: formato existente `{"error": {"code", "message", "fields"}}`, con los códigos
  de [contracts/api.md](contracts/api.md). Los errores dentro del callback se guardan en
  `OAuthAttempt.error` y se muestran en el HTML.
- **Fallos transitorios**: los errores de red, `5xx` y `429` de Google o YouTube **nunca**
  cambian el estado de conexión (`youtube_unavailable`).
- **Núcleo de cuentas independiente** (Constitution III, análisis C1, opción A):
  - `backend/app/accounts.py`, `AccountRead` y el modelo `Account` **no se modifican**;
  - `accounts.py` no importa nada de `app.youtube_*`;
  - `Account` no declara una relación inversa;
  - el frontend consulta `GET /api/accounts/{id}/youtube-connection` solo para cuentas
    YouTube.
- **Configuración OAuth**: se lee en cada operación; no requiere reiniciar el backend. El
  estado de conexión expone solo el booleano `oauth_configured`.
- **Datos existentes**: `Account`, `Project` y `Publication` no cambian en base de datos.
  Ninguna operación de esta feature borra cuentas ni publicaciones.
- **Endpoints**: síncronos (`def`), como en el resto del proyecto. El estado compartido en
  memoria se protege con `threading.Lock`.
- **Catálogos**: `YouTubeConnectionStatus` y los estados de `OAuthAttempt` se duplican en
  backend (`StrEnum`) y frontend (`types.ts`), con un comentario en cada lado que apunte al
  otro.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: línea base y dependencias nuevas.

- [X] T001 Verify the baseline on branch `005-youtube-oauth-connection`: run `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/` and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`. All must pass before any change; record any pre-existing failure instead of fixing it silently.
- [X] T002 Add `keyring>=25` as a **new runtime dependency** and move `httpx2` from the `dev` group to runtime `dependencies` in `backend/pyproject.toml`, then run `uv lock && uv sync` to update `backend/uv.lock`. Check that `uv run python -c "import keyring, httpx2"` works. If mypy reports missing types for `keyring`, add a `[[tool.mypy.overrides]]` with `ignore_missing_imports = true` scoped to `keyring.*` only.
- [X] T003 [P] Add `client_secret*.json` and `google-oauth-client*.json` under the "Secrets and credentials" block of `.gitignore`, and confirm with `git check-ignore -v backend/data/google-oauth-client.json`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: configuración, errores, modelo y migración, almacén seguro, lógica OAuth pura,
gateway de Google, cableado de la app, fakes de test y tipos y cliente del frontend.

**⚠️ CRITICAL**: no se puede empezar ninguna historia hasta completar esta fase.

### Tests fundacionales (escribir primero)

- [X] T004 [P] Create `backend/tests/fakes.py`:
  - **`InMemoryCredentialStore`**:
    - implements the `CredentialStore` protocol (`get`, `set`, `delete`) with a dict;
    - an `unavailable` flag that makes every call raise `CredentialStoreUnavailable`;
    - a `secrets` property for assertions.
  - **`FakeGoogle`**:
    - a programmable handler for an `httpx2.MockTransport` that serves
      `POST https://oauth2.googleapis.com/token` (both `authorization_code` and
      `refresh_token` grants) and `GET https://www.googleapis.com/youtube/v3/channels`;
    - configurable outcomes: success with given tokens, scopes and expiry; missing
      `refresh_token`; partial `scope`; `400 invalid_grant`; other `400` errors; `5xx`;
      `429`; timeout (raise `httpx2.ConnectTimeout`); 0, 1 or 2 channels; `401` and
      `403 insufficientPermissions` on `channels`;
    - records every request (method, URL, form body, headers) so tests can assert that a
      `code_verifier` was sent, that no token appears in a URL, and that no request was
      made at all (e.g. on disconnect);
    - any request to an unexpected URL, including `oauth2.googleapis.com/revoke`, fails the
      test.
  - **Constants**: distinctive fake secret values (`FAKE_ACCESS_TOKEN`,
    `FAKE_REFRESH_TOKEN`, `FAKE_AUTH_CODE`, `FAKE_CLIENT_SECRET`), reused by the leak tests.
- [X] T005 Extend `backend/tests/conftest.py`:
  - **Fixtures**:
    - `oauth_client_file`: writes a fake Desktop-app client JSON
      `{"installed": {"client_id": "test-client-id.apps.googleusercontent.com", "client_secret": FAKE_CLIENT_SECRET, ...}}`
      into `tmp_path` and sets `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE` via `monkeypatch`;
    - `credential_store`: an `InMemoryCredentialStore`;
    - `fake_google`: a `FakeGoogle`;
    - `youtube_client`: a `TestClient(create_app(db_path, media_dir, credential_store=..., google_transport=httpx2.MockTransport(fake_google.handle)))`.
  - **Autouse safety fixture**: saves `original = keyring.get_keyring()`, calls
    `keyring.set_keyring(keyring.backends.fail.Keyring())` and, on teardown, restores it
    with `keyring.set_keyring(original)`. No test ever touches the real system keyring. It
    must **not** monkeypatch `keyring.get_keyring`, so the credential-store tests (T007) can
    replace the backend with their own `keyring.set_keyring(...)` calls.
  - **Helpers**:
    - `authorize(client, account_id)`: returns the authorize JSON and the parsed `state`
      from `authorization_url`;
    - `complete_callback(client, state, code=FAKE_AUTH_CODE, scope=...)`;
    - `connect_youtube(client, fake_google, account_id, channel_id="UC_TEST_1", title="Cyber Channel")`:
      runs authorize, callback and attempt polling, and returns the connection JSON.

  Depends on T004.
- [X] T006 [P] Write `backend/tests/test_youtube_oauth.py` (pure unit tests, fail before
  T013):
  - **PKCE**:
    - `generate_pkce_pair()` returns a verifier of 43–128 chars from
      `[A-Za-z0-9-._~]`;
    - `challenge == base64url(sha256(verifier))` without padding;
    - two calls differ.
  - **`state`**: `generate_state()` is ≥ 43 chars and unique per call.
  - **`build_authorization_url(...)`**:
    - targets `https://accounts.google.com/o/oauth2/v2/auth`;
    - has exactly the params `response_type=code`, `client_id`, `redirect_uri`,
      `scope="https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload"`,
      `state`, `code_challenge`, `code_challenge_method=S256`, `access_type=offline` and
      `prompt="select_account consent"`;
    - never contains the verifier;
    - has no `include_granted_scopes`.
  - **`load_client_config()`**: raises `OAuthNotConfigured` for a missing file, invalid
    JSON, a `web` client, or a missing `client_id` or `client_secret`, and returns the
    config for a valid `installed` file.
  - **`get_oauth_redirect_uri()`**:
    - default `http://127.0.0.1:8000/api/youtube/oauth/callback`;
    - accepts `http://[::1]:9000/x`;
    - rejects `https://…`, `http://localhost:8000/…` and non-loopback hosts.
  - **`OAuthAttemptRegistry`**:
    - `create` → `pending` with `expires_at = now + 10 min`;
    - `consume_state` returns the attempt once, then `None` (single use);
    - an unknown state → `None`;
    - **single expiry and retention rule** (inject a clock):
      - at `expires_at` + 1 s, `consume_state` → `None` and `get(attempt_id)` returns the
        attempt with status `expired`, `finished_at` set and no secrets;
      - it is still returned as `expired` at `finished_at + 9 min 59 s`;
      - at `finished_at + 10 min` + 1 s, `get` → `None` (purged);
      - the same retention applies to `completed`, `failed` and `cancelled` attempts;
    - a new `create` for the same account expires the previous pending one;
    - terminal transitions clear `code_verifier` and `pending_credentials`;
    - `get(attempt_id)` never exposes those fields through `to_read()`.
- [X] T007 [P] Write `backend/tests/test_credential_store.py` (fail before T012), using fake
  backend classes installed with `keyring.set_keyring(...)` inside each test. This
  overrides the `fail.Keyring` set by the autouse fixture of T005, whose teardown restores
  the original backend. Include one test proving that, with only the autouse fixture
  active, `KeyringCredentialStore` raises `CredentialStoreUnavailable`.
  Cases:
  - **Accepted**: allow-listed backends (`SecretService.Keyring`, `macOS.Keyring`,
    `Windows.WinVaultKeyring`, `libsecret.Keyring`, `kwallet.DBusKeyring`) and a
    `ChainerBackend` made only of allowed backends. With them, `set`, `get` and `delete`
    round-trip, and `delete` of a missing ref is not an error.
  - **Rejected**, each with `CredentialStoreUnavailable` and **no write** to any backend:
    `fail.Keyring`, `null.Keyring`, a class from a module named `keyrings.alt.file`, an
    unknown third-party class, and a chainer that contains one insecure backend.
  - **Errors**: `keyring.errors.KeyringLocked`, `InitError` and generic `KeyringError` raised
    by the backend on `set`, `get` or `delete` → `CredentialStoreUnavailable`.
  - **Leak check**: the error message never contains the secret value.
- [X] T008 [P] Write `backend/tests/test_youtube_gateway.py` (fail before T014), running
  `GoogleGateway` against `httpx2.MockTransport(FakeGoogle)`:
  - **`exchange_code(code, code_verifier, redirect_uri, client)`**:
    - posts a form with `grant_type=authorization_code`, `code`, `code_verifier`,
      `client_id`, `client_secret` and `redirect_uri`;
    - returns a `TokenSet` with `access_token`, `refresh_token`, an aware UTC `expires_at`
      and `scopes`;
    - `400` → `GoogleRejected`; `5xx`, `429` or timeout → `GoogleUnavailable`.
  - **`refresh(refresh_token, client)`**:
    - success keeps the old refresh token unless a new one is returned;
    - `400 {"error": "invalid_grant"}` → `InvalidGrant`;
    - other `400` → `GoogleRejected`;
    - `5xx`, `429` or timeout → `GoogleUnavailable`.
  - **`list_my_channels(access_token)`**:
    - calls `GET .../channels?part=snippet&mine=true&maxResults=50` with
      `Authorization: Bearer …` (token not in URL);
    - maps `id`, `snippet.title`, `snippet.customUrl` and
      `snippet.thumbnails.default.url` to `ChannelInfo`;
    - `401` → `GoogleUnauthorized`; `403` → `GoogleForbidden`; `5xx`, `429` or timeout →
      `GoogleUnavailable`.
  - **Safety**:
    - no gateway exception message contains any fake secret;
    - `GoogleGateway` has no `revoke` method;
    - with `caplog` at DEBUG, no fake secret appears in the logs.
- [X] T009 [P] Extend `backend/tests/test_migrations.py` (fail before T011):
  - upgrading a database populated at revision `0003` (project, YouTube and Instagram
    accounts, content and publication) to `0004` keeps all rows and creates
    `youtube_connections`;
  - inserting two rows with the same `account_id` fails;
  - inserting two rows with the same `(project_id, channel_id)` fails;
  - the same `channel_id` in different projects succeeds;
  - a status other than `connected` or `reconnect_required` fails the `CHECK`;
  - a duplicate `credential_ref` fails;
  - the constraint names in the migrated database are exactly the ones in
    [data-model.md](data-model.md) (`uq_youtube_connections_account_id`,
    `uq_youtube_connections_project_id_channel_id`,
    `uq_youtube_connections_credential_ref`, `ck_youtube_connections_status`,
    `fk_youtube_connections_account_id_accounts`,
    `fk_youtube_connections_project_id_projects`);
  - the existing models-vs-migrations drift test still passes (same names in the model and
    the migration).

### Implementación fundacional

- [X] T010 Extend `backend/app/config.py` and `backend/app/errors.py`:
  - **`config.py`**:
    - `get_google_oauth_client_file()`: env `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`, else
      `BACKEND_DIR / "data" / "google-oauth-client.json"`;
    - `get_oauth_redirect_uri()`: env `AUTOPUBLISHER_OAUTH_REDIRECT_URI`, default
      `http://127.0.0.1:8000/api/youtube/oauth/callback`. Validated: scheme `http` and host
      `127.0.0.1` or `[::1]`, otherwise `ValueError` with a clear message;
    - `OAUTH_ATTEMPT_TTL = timedelta(minutes=10)` (validity) and
      `OAUTH_ATTEMPT_RETENTION = timedelta(minutes=10)` (how long a terminal attempt is
      kept, without secrets, after `finished_at`).
  - **`errors.py`**:
    - `AppError(status_code: int, code: str, message: str)` and its handler, using
      `error_response`;
    - extend `ConflictCode` with `platform_not_supported`, `channel_already_connected`,
      `connection_changed`, `not_connected`, `reconnect_required` and
      `oauth_attempt_not_confirmable`;
    - register the handler in `register_error_handlers`;
    - keep existing behaviour unchanged.
- [X] T011 Add `YouTubeConnectionStatus(StrEnum)` (`connected`, `reconnect_required`;
  comment pointing to `frontend/src/types.ts`) and the `YouTubeConnection` model in
  `backend/app/models.py`:
  - **Columns** per [data-model.md](data-model.md): `account_id` FK `RESTRICT` unique,
    `project_id` FK `RESTRICT`, `channel_id` String(64), `channel_title` String(200),
    `channel_handle` String(100) nullable, `channel_thumbnail_url` String(500) nullable,
    `status` String(20), `credential_ref` String(64) unique, `connected_at`,
    `last_verified_at` (nullable) and `updated_at` as `UTCDateTime`.
  - **Constraints**: `UniqueConstraint("project_id", "channel_id")` and
    `CheckConstraint("status IN ('connected', 'reconnect_required')", name="status")`.
  - **No relationship on `Account`**: the common `Account` model is **not** modified (no
    inverse relationship); `YouTubeConnection` only has the FK `account_id`.
  - **Migration**: write `backend/migrations/versions/0004_create_youtube_connections.py`
    with `down_revision = "0003"`, creating the same table and constraints with **exactly
    the same names** the model's naming convention produces (explicit names listed in
    [data-model.md](data-model.md)). Makes T009 pass.
- [X] T012 [P] Implement `backend/app/credential_store.py`:
  - **Protocol**: `CredentialStore` (`get(ref) -> str | None`, `set(ref, value)`,
    `delete(ref)`).
  - **Exception**: `CredentialStoreUnavailable` with a fixed message (never the value).
  - **Allow-list**: `ALLOWED_BACKENDS` with the fully-qualified class names of research §8.
  - **`ensure_secure_backend(backend)`**: accepts allow-listed classes, and a
    `ChainerBackend` only if every chained backend is allowed.
  - **`KeyringCredentialStore(service="autopublisher.youtube")`**:
    - calls `ensure_secure_backend(keyring.get_keyring())` before **every** operation;
    - wraps `keyring.errors.KeyringError` (including `KeyringLocked` and `InitError`) into
      `CredentialStoreUnavailable`;
    - treats `PasswordDeleteError` for a missing entry as success;
    - has no fallback of any kind.

  Makes T007 pass.
- [X] T013 [P] Implement `backend/app/youtube_oauth.py` (pure logic, no HTTP):
  - **Constants**: `AUTH_ENDPOINT`, `SCOPES` (the two scopes from research §3) and
    `REQUIRED_SCOPES`.
  - **Generators**: `generate_state()` (`secrets.token_urlsafe(32)`) and
    `generate_pkce_pair()` (`secrets.token_urlsafe(64)`, S256 challenge).
  - **`build_authorization_url(client_id, redirect_uri, state, code_challenge)`**: always
    includes `access_type=offline` and `prompt="select_account consent"`.
  - **Client config**: `OAuthClientConfig` dataclass and `load_client_config(path)`, which
    raises `OAuthNotConfigured`. The config's `__repr__` must not include the secret.
  - **Dataclasses**: `ChannelSummary` (`id`, `title`, `handle`, `thumbnail_url`).
  - **`OAuthAttempt`**:
    - fields: `attempt_id`, `account_id`, `state`, `code_verifier`, `created_at`,
      `expires_at`, `status`, `error`, `current_channel`, `new_channel`,
      `pending_credentials`, `pending_channel_info`;
    - `to_read()` exposes only the public fields of [contracts/api.md](contracts/api.md).
  - **`OAuthAttemptRegistry(clock=utc_now)`**: methods `create`, `consume_state`, `get`,
    `finish(attempt, status, error=None, connection=None)` (clears the secrets),
    `await_confirmation` and `expire_for_account`. It holds a single `threading.Lock`.
    On every call it first moves non-terminal attempts past `expires_at` to `expired`
    (setting `finished_at` and clearing secrets), then purges only the terminal attempts
    past `finished_at + OAUTH_ATTEMPT_RETENTION`. It never purges an attempt before its
    retention ends.

  Makes T006 pass.
- [X] T014 [P] Implement `backend/app/youtube_gateway.py`:
  - **Dataclasses**:
    - `TokenSet`, with `to_json()`/`from_json()` for the secret store (fields
      `access_token`, `refresh_token`, `expires_at` ISO UTC, `scopes`) and a redacted
      `__repr__`;
    - `ChannelInfo`.
  - **Exceptions**: `GoogleRejected`, `InvalidGrant`, `GoogleUnavailable`,
    `GoogleUnauthorized` and `GoogleForbidden`, all with fixed messages.
  - **`GoogleGateway(client: httpx2.Client)`**: methods `exchange_code`, `refresh` and
    `list_my_channels`, as tested in T008. It parses Google's JSON error code but never
    logs or stores bodies, and has no `revoke` method.

  Makes T008 pass.
- [X] T015 Add Pydantic schemas in `backend/app/schemas.py`:
  - `YouTubeChannelRead` (`id`, `title`, `handle`, `thumbnail_url`);
  - `YouTubeConnectionRead` (`status`: `not_connected` | `connected` |
    `reconnect_required`, `channel`, `connected_at`, `last_verified_at`,
    `oauth_configured: bool`);
  - `AuthorizeRead` (`attempt_id`, `authorization_url`, `expires_at`);
  - `OAuthAttemptErrorRead` (`code`, `message`);
  - `OAuthAttemptRead` (`attempt_id`, `account_id`, `status`, `expires_at`, `error`,
    `current_channel`, `new_channel`, `connection`);
  - **`AccountRead` is not modified.**

  Depends on T011.
- [X] T016 Create `backend/app/youtube_connections.py` with the router skeleton
  (`APIRouter(prefix="/api", tags=["youtube"])`) and shared helpers:
  - **Lookups**:
    - `get_youtube_account_or_error(session, account_id)`: `NotFoundError`, then
      `ConflictError("platform_not_supported")`;
    - `get_connection(session, account_id)`: queries `YouTubeConnection` by `account_id`
      (no ORM relationship on `Account`);
    - `oauth_configured()`: `True` if `load_client_config(get_google_oauth_client_file())`
      succeeds, `False` on `OAuthNotConfigured`. Evaluated on every call (no restart
      needed) and exposes only the boolean;
    - `connection_to_read(conn | None)`: includes `oauth_configured`.
  - **Dependencies**: `get_credential_store(request)`, `get_gateway(request)` and
    `get_registry(request)`, which read `request.app.state`.
  - **Route**: `GET /api/accounts/{account_id}/youtube-connection` (contract), which never
    contacts Google. Add tests to `backend/tests/test_youtube_connect.py`: `not_connected`
    with `oauth_configured: true` when the client file exists; `oauth_configured: false`
    without it, then `true` after writing it with the same running app (no restart); the
    response never contains the client ID, the secret or the file path.
  - **Wiring in `backend/app/main.py`**:
    - `create_app(db_path=None, media_dir=None, *, credential_store=None, google_transport=None)`;
    - in `lifespan`: build `httpx2.Client(transport=google_transport, timeout=10)` (closed
      on shutdown), `GoogleGateway`, `OAuthAttemptRegistry()`, and
      `credential_store or KeyringCredentialStore()` on `app.state`;
    - `app.include_router(youtube_connections.router)`.

  Depends on T010–T015.
- [X] T017 Guard the independence of the accounts core (Constitution III, analysis C1,
  option A). **Do not modify** `backend/app/accounts.py`, `AccountRead` or the `Account`
  model. Add to `backend/tests/test_accounts.py`:
  - the JSON keys of `GET /api/projects/{id}/accounts` items are exactly the existing
    `AccountRead` fields, for YouTube and Instagram accounts alike (no `youtube_connection`
    or other YouTube field);
  - an architectural test that inspects `app.accounts` (e.g. via `ast` over its source)
    and asserts it imports no `app.youtube_*` module and nothing from `app.youtube_*`;
  - `Account` has no attribute `youtube_connection`.

  Depends on T016.
- [X] T018 [P] Frontend foundations:
  - **`frontend/src/types.ts`**:
    - `YouTubeConnectionStatus` with `YOUTUBE_CONNECTION_STATUS_LABELS` (`Not connected`,
      `Connected`, `Reconnect required`) and a comment pointing to `backend/app/models.py`;
    - `YouTubeChannel`, `YouTubeConnection` (including `oauth_configured: boolean`),
      `OAuthAttemptStatus` and `OAuthAttempt`;
    - `Account` is **not** modified.
  - **`frontend/src/api.ts`**: `getYouTubeConnection(accountId)`,
    `authorizeYouTube(accountId)`, `getOAuthAttempt(attemptId)`,
    `confirmOAuthAttempt(attemptId)`, `cancelOAuthAttempt(attemptId)`,
    `verifyYouTubeConnection(accountId)` and `disconnectYouTube(accountId)`, using the
    existing `request` helper and the routes of [contracts/api.md](contracts/api.md).
  - **`frontend/src/test-fake-api.ts`**:
    - in-memory connection per YouTube account id, served by `getYouTubeConnection`
      (`not_connected` by default; `platform_not_supported` for other platforms), and a
      call log so tests can assert which accounts were queried;
    - an `oauthConfigured` flag (default `true`) reflected in every `YouTubeConnection`;
    - programmable attempts (`nextAttemptOutcome`: `completed` with a channel, `failed`
      with an error, or `awaiting_confirmation` with current/new channels);
    - basic rules (inactive → `account_inactive`/`project_inactive`, missing config →
      `oauth_not_configured`).

**Checkpoint**: `uv run pytest` passes T006–T009 and the existing suite. The migration
applies, `GET .../youtube-connection` answers, and the frontend typechecks. The user stories
can start.

---

## Phase 3: User Story 1 - Conectar una cuenta YouTube con su canal real (Priority: P1) 🎯 MVP

**Goal**: `Connect` → Google → callback → canal identificado → `Connected`, con credenciales
solo en el almacén seguro y persistentes tras un reinicio.

**Independent Test**: con fakes, iniciar la conexión de una cuenta YouTube activa, completar
el callback y comprobar:

- que el intento termina en `completed`;
- que la cuenta muestra `connected` con título y channel ID;
- que el almacén tiene el secreto con `credential_ref`;
- que SQLite no contiene ningún token;
- que todo sigue igual tras reabrir la app.

### Tests for User Story 1

- [X] T019 [P] [US1] Write `backend/tests/test_youtube_connect.py`, happy path:
  - **authorize**:
    - `POST /api/accounts/{id}/youtube-connection/authorize` → `201` with `attempt_id`,
      `authorization_url` (params as in T006, `client_id` from the fake file) and
      `expires_at`;
    - `GET` attempt → `pending`.
  - **Callback** `GET /api/youtube/oauth/callback?state=…&code=…&scope=…` → `200`
    `text/html` containing "connected".
  - **`FakeGoogle` assertions**: it received the `code_verifier` matching the
    `code_challenge` from the URL.
  - **Attempt** → `completed` with `connection.status == "connected"` and channel
    `id`/`title`/`handle`/`thumbnail_url` from the fake.
  - **Status**: `GET .../youtube-connection` shows the same data and `connected_at` is
    set.
  - **FR-017**: after connecting, `GET /api/projects/{id}/accounts` returns the account
    with the **same** `handle` and `display_name` as before (and an unchanged
    `updated_at`), even when the channel's handle and title differ from them.
  - **Store**: holds exactly one secret under the row's `credential_ref`, whose JSON has
    both tokens.
  - **Rejections**: authorize for an Instagram account → `409 platform_not_supported`; for
    an unknown account → `404 not_found`; without the client file → `503
    oauth_not_configured`, with no attempt created.
  - **Inactive at callback time** (U2, implemented from US1): an attempt created while
    active whose account (or project) is deactivated before the callback → attempt
    `failed` with `account_inactive` (`project_inactive`), no request to the token
    endpoint, and the store unchanged.
- [X] T020 [P] [US1] Write `backend/tests/test_youtube_secrets.py`, covering **only the
  Connect flow** (authorize, callback, attempt polling and status). T032 and T036 add their
  own cases for Disconnect and Verify to this file. Provide a reusable helper
  `assert_no_secrets(db_path, responses, caplog, fake_google, extra=())`. After a full
  connect, none of the fake secrets (`FAKE_ACCESS_TOKEN`, `FAKE_REFRESH_TOKEN`,
  `FAKE_AUTH_CODE`, `FAKE_CLIENT_SECRET`, and the `code_verifier` taken from the
  `FakeGoogle` token request) appears in:
  - the full SQLite dump (`sqlite3` `iterdump()` of `db_path`);
  - any JSON response body or callback HTML returned during the flow;
  - `caplog.text` at DEBUG;
  - any URL recorded by `FakeGoogle`.
- [X] T021 [P] [US1] Extend `backend/tests/test_persistence.py`: connect with a shared
  `InMemoryCredentialStore`, close the `TestClient`, open a new
  `create_app(db_path, media_dir, credential_store=same_store, ...)`, and check that the
  account is still `connected` with the same channel and that the secret is still
  retrievable via `credential_ref`.

### Implementation for User Story 1

- [X] T022 [US1] In `backend/app/youtube_connections.py`, implement
  `POST /api/accounts/{account_id}/youtube-connection/authorize`:
  1. YouTube account check;
  2. `ensure_account_connectable(account)`, a new helper in the same module: project
     inactive → `ConflictError("project_inactive", ...)`; account inactive →
     `ConflictError("account_inactive", ...)`;
  3. `load_client_config` (`OAuthNotConfigured` → `AppError(503, "oauth_not_configured", ...)`);
  4. `get_oauth_redirect_uri()`;
  5. `generate_state` / `generate_pkce_pair`;
  6. `registry.create(...)`, which expires any previous pending attempt of the account and
     records `current_channel` from the existing row, if any;
  7. return `AuthorizeRead`, status `201`.

  Also implement `GET /api/youtube/oauth/attempts/{attempt_id}` → `OAuthAttemptRead`, or
  `AppError(404, "oauth_attempt_not_found", ...)`.
- [X] T023 [US1] In `backend/app/youtube_connections.py`, implement
  `complete_connection(session, store, account, channel: ChannelInfo, tokens: TokenSet) -> YouTubeConnection`
  (research §10, plan Design Notes):
  1. `new_ref = uuid4().hex`;
  2. `store.set(new_ref, tokens.to_json())`;
  3. insert or update the row (`status=connected`, channel fields,
     `connected_at=last_verified_at=updated_at=utc_now()`, `project_id=account.project_id`)
     and `commit`;
  4. on any failure after `store.set` (including `IntegrityError`, re-raised as a conflict
     and refined in US6), roll back and immediately try `store.delete(new_ref)`. If that
     delete also fails (store unavailable), log only `account_id` and accept the orphan
     entry: no later detection or cleanup is attempted (spec FR-025);
  5. on success, `store.delete(old_ref)` best-effort, with the same rule if it fails.

  `CredentialStoreUnavailable` → `AppError(503, "credential_store_unavailable", ...)`, with
  no row written.
- [X] T024 [US1] In `backend/app/youtube_connections.py`, implement
  `GET /api/youtube/oauth/callback` (`response_class=HTMLResponse`), happy path, in the
  contract order:
  1. consume `state` (unknown → `400` HTML `oauth_state_invalid`, no side effects);
  2. require `code`;
  3. load the account and call `ensure_account_connectable(account)` **before** any
     request to Google (U2: implemented here from US1, not deferred to US7);
  4. load the client config;
  5. `gateway.exchange_code(code, attempt.code_verifier, redirect_uri, client)`;
  6. check `REQUIRED_SCOPES ⊆ tokens.scopes` (`oauth_scope_insufficient`) and that
     `refresh_token` is present (`oauth_offline_access_missing`);
  7. `gateway.list_my_channels(...)`, requiring exactly one channel
     (`youtube_no_channel` / `youtube_channel_ambiguous`);
  8. `complete_connection`;
  9. `registry.finish(attempt, "completed", connection=...)`.

  Render the result page with `render_callback_page(title, message, ok)`: inline minimal
  HTML, `html.escape` on all text, no scripts and no external resources, telling the user
  to close the tab and return to AutoPublisher. Map every handled failure to
  `registry.finish(attempt, "failed", error={code, message})` plus an error page (`400`).
- [X] T025 [P] [US1] Create `frontend/src/components/YouTubeConnectionPanel.tsx`, base
  version. Props: `account` and `projectActive`.
  - **Loading**: on mount (and via an internal `reload()`), call
    `getYouTubeConnection(account.id)`; show a loading state and API errors.
  - **Display**:
    - a status badge from `YOUTUBE_CONNECTION_STATUS_LABELS`;
    - when a channel exists: the thumbnail (if any, with `alt` = title), the title, the
      handle (if any) and `Channel ID: <id>`, plus the localized `connected_at` via
      `formatDate`.
  - **Not configured** (`oauth_configured === false`): **Connect** does not open any tab
    or call `authorizeYouTube`. The panel shows "YouTube OAuth is not configured." with the
    key steps (create a Desktop app OAuth client in Google Cloud and save its JSON as
    `backend/data/google-oauth-client.json`) and a pointer to the README section
    "Connecting YouTube".
  - **Connect** (shown when `not_connected` and `oauth_configured === true`):
    1. open a blank tab synchronously in the click handler
       (`window.open("", "_blank")`);
    2. call `authorizeYouTube`;
    3. set `tab.location.href = authorization_url`, or render an
       "Open Google authorization" link when the tab is `null`;
    4. **secondary defence**: if `authorizeYouTube` throws before the tab is navigated,
       call `tab?.close()` and show the error.
  - **Polling**: poll `getOAuthAttempt` every 2 s with `setTimeout` until
    `completed`/`failed`/`cancelled`/`expired`/`awaiting_confirmation`, cleaning up on
    unmount.
  - **Result**: on `completed`, `reload()` the connection; on `failed`, show `attempt.error.message`
    in a `role="alert"` element. API errors use `toApiError(...).message`.
  - Add minimal styles in `frontend/src/index.css`.
- [X] T026 [US1] Render `YouTubeConnectionPanel` **only** for
  `account.platform === "youtube"` in `frontend/src/components/AccountList.tsx`, with the
  new prop `projectActive`. In `frontend/src/components/ProjectDetail.tsx`, pass
  `project.is_active`. Other platforms render exactly as before and never trigger a
  connection request.
- [X] T027 [P] [US1] Write `frontend/src/components/YouTubeConnectionPanel.test.tsx`, using
  fake timers and `vi.spyOn(window, "open")`:
  - a YouTube account shows "Not connected" and **Connect**;
  - an Instagram account in `AccountList` shows no panel, and the fake API log shows no
    `getYouTubeConnection` call for it (only YouTube accounts are queried);
  - clicking **Connect** opens a tab and sets its location to the authorization URL;
  - when the polled attempt becomes `completed`, the panel reloads and shows "Connected",
    the channel title and the channel ID;
  - a `null` tab shows the fallback link;
  - **`oauth_configured: false`**: the setup instructions are shown, and clicking
    **Connect** calls neither `window.open` nor `authorizeYouTube`;
  - **secondary defence**: with `oauth_configured: true` but `authorizeYouTube` rejecting
    with `oauth_not_configured`, the opened tab's `close()` is called and the error
    message is shown.

**Checkpoint**: US1 works end to end with fakes, and with Google real according to
quickstart §3 steps 1–7.

---

## Phase 4: User Story 2 - Manejar cancelaciones y errores de la autorización (Priority: P1)

**Goal**: cada fallo del flujo OAuth produce un mensaje comprensible, deja la cuenta en su
estado previo y no deja ninguna credencial almacenada.

**Independent Test**: con `FakeGoogle`, provocar cancelación, `state` desconocido, usado o
caducado, callback sin `code`, intercambio rechazado, YouTube caído, scopes parciales, sin
refresh token y 0 o 2 canales. Comprobar el error en el intento y en el HTML, el estado de la
cuenta sin cambios y el almacén vacío.

### Tests for User Story 2

- [X] T028 [P] [US2] Add error-path tests to `backend/tests/test_youtube_connect.py`
  (parametrized where possible). For each case, assert the attempt `status`/`error.code`,
  the HTML status code, that the account status is unchanged (`not_connected`, or still
  `connected` with the old channel), that the store is unchanged, and that
  `FakeGoogle.requests` matches the expectation:
  - **No exchange**:
    - `error=access_denied` → `oauth_cancelled`;
    - `error=server_error` → `oauth_provider_error`;
    - missing `code` → `oauth_callback_invalid`.
  - **`state` rejected** (`oauth_state_invalid`, `400`, no Google call):
    - missing `state`;
    - unknown `state`;
    - reused `state` (second callback after success);
    - expired attempt (registry clock advanced 11 min);
    - a superseded attempt (a second authorize for the same account).
  - **Exchange or YouTube failures**:
    - token endpoint `400` → `oauth_exchange_failed`;
    - token endpoint `5xx`/timeout → `youtube_unavailable`;
    - partial `scope` → `oauth_scope_insufficient`;
    - no `refresh_token` → `oauth_offline_access_missing`;
    - channels `5xx` → `youtube_unavailable`;
    - 0 channels → `youtube_no_channel`;
    - 2 channels → `youtube_channel_ambiguous`, with no channel stored and the first one
      **not** picked;
    - `CredentialStoreUnavailable` on `set` → `credential_store_unavailable`, with no row.
  - **HTTP status of the callback page**: every expected OAuth or validation error above →
    `400`; an unexpected exception (monkeypatch `list_my_channels` to raise
    `RuntimeError`) → attempt `failed` with `internal_error`, page `500` with a generic
    message that contains no exception text.
  - **Never**: a request to a revoke URL.
- [X] T029 [P] [US2] Add to `frontend/src/components/YouTubeConnectionPanel.test.tsx`: a
  polled attempt that ends `failed` with `oauth_cancelled` shows its message and keeps
  **Connect** available; `expired` shows "The authorization expired. Try again."; a
  `404 oauth_attempt_not_found` during polling shows the same message and stops polling.

### Implementation for User Story 2

- [X] T030 [US2] Harden the callback in `backend/app/youtube_connections.py` to satisfy
  T028:
  - **Exception mapping**:
    - `GoogleRejected` → `oauth_exchange_failed`;
    - `GoogleUnavailable` → `youtube_unavailable`;
    - `GoogleUnauthorized` / `GoogleForbidden` during identification →
      `oauth_exchange_failed`;
    - `CredentialStoreUnavailable` → `credential_store_unavailable`;
    - `OAuthNotConfigured` → `oauth_not_configured`.
  - **Provider errors**: map the `error` param (`access_denied` → `oauth_cancelled`, others
    → `oauth_provider_error`).
  - **Other paths**: handle missing `state`/`code`, and catch unexpected exceptions →
    `failed`/`internal_error` with a generic message, logged without secrets.
  - **HTTP status of the HTML page**: `200` for `completed`/`awaiting_confirmation`, `400`
    for every expected OAuth or validation error, and `500` only for `internal_error`
    ([contracts/api.md](contracts/api.md)).
  - **Messages**: use the fixed English messages from [contracts/api.md](contracts/api.md)
    (the multi-channel message must ask to select the right channel in Google's account
    chooser and retry).
  - **Discarded credentials**: are only dropped from memory, never stored and never revoked.
- [X] T031 [US2] In `frontend/src/components/YouTubeConnectionPanel.tsx`, show
  user-friendly text for terminal non-success attempts (`failed` → `error.message`;
  `expired` → "The authorization expired. Try again."; `cancelled` → nothing). Re-enable the
  connect button and stop polling. A `404 oauth_attempt_not_found` while polling (attempt
  already purged or backend restarted) is treated like `expired`: same message, polling
  stops, and the connection is reloaded.

**Checkpoint**: US1 + US2 cover the complete connection flow and all its errors.

---

## Phase 5: User Story 3 - Desconectar una cuenta YouTube (Priority: P1)

**Goal**: `Disconnect` borra siempre el secreto local y la fila, sin contactar con Google,
conservando la cuenta y sus publicaciones, y explica cómo retirar el permiso en Google.

**Independent Test**: conectar, crear una publicación de la cuenta y desconectar.
Comprobar `not_connected`, el almacén vacío, la fila borrada, la cuenta y la publicación
intactas, y cero peticiones a Google.

### Tests for User Story 3

- [X] T032 [P] [US3] Write `backend/tests/test_youtube_disconnect.py`:
  - **Happy path**: `POST /api/accounts/{id}/youtube-connection/disconnect` on a connected
    account → `200 {"status": "not_connected", ...}`, then:
    - the secret is gone from the store and the row from `youtube_connections`;
    - the account fields (`handle`, `display_name`, `is_active`, `updated_at`) and its
      existing publication are unchanged;
    - `FakeGoogle.requests` is empty for this call (no revoke, no network).
  - **Other states**:
    - works on a `reconnect_required` row;
    - works without the client file;
    - works with an inactive account and with an inactive project;
    - is idempotent on `not_connected` (`200`);
    - a missing secret in the store is not an error.
  - **Rejections**: `404` for an unknown account and `409 platform_not_supported` for
    Instagram.
  - **Store failure**: with the store `unavailable`, the response is
    `503 credential_store_unavailable`, the row and its `credential_ref` are **kept**, and
    `GET .../youtube-connection` still shows the previous status and channel. After making
    the store available again, a retry succeeds and only then the row disappears.
  - **Order**: a store whose `delete` raises leaves the row untouched (the row is deleted
    only after a successful secret deletion).
  - **Pending attempts**: a pending attempt of that account becomes `expired`.
  - **Leaks**: add Disconnect cases to `backend/tests/test_youtube_secrets.py` (reusing
    `assert_no_secrets`): no fake secret in the disconnect response, the logs or the
    database after disconnecting.
- [X] T033 [P] [US3] Add to `frontend/src/components/YouTubeConnectionPanel.test.tsx`:
  - **Disconnect** appears when `connected` and when `reconnect_required`;
  - it asks for confirmation (`window.confirm` mocked);
  - after success, it shows "Not connected" and the note linking to
    `https://myaccount.google.com/connections`, which warns that removing access there
    affects every AutoPublisher connection using that Google account;
  - cancelling the confirm does nothing.

### Implementation for User Story 3

- [X] T034 [US3] Implement `POST /api/accounts/{account_id}/youtube-connection/disconnect`
  in `backend/app/youtube_connections.py` (plan Design Notes, research §13):
  1. load the row (none → return `not_connected`);
  2. `store.delete(credential_ref)` (unavailable → `503 credential_store_unavailable`,
     row and reference kept for a retry; a missing secret is not an error);
  3. **only after step 2 succeeds**, delete the row and `commit`;
  4. `registry.expire_for_account(account_id)`;
  5. return `connection_to_read(None)`.

  No gateway call and no client config load.
- [X] T035 [US3] Add **Disconnect** to `frontend/src/components/YouTubeConnectionPanel.tsx`:
  - `window.confirm("Disconnect this YouTube channel? AutoPublisher will delete its stored credentials.")`;
  - call `disconnectYouTube`, then `reload()`;
  - show the note "AutoPublisher deleted its stored credentials. To fully remove
    AutoPublisher's access to your Google account, go to myaccount.google.com/connections.
    This affects every AutoPublisher connection that uses that Google account.", with a
    link (`target="_blank" rel="noreferrer"`);
  - always enabled when a connection exists, even if the account or project is inactive.

**Checkpoint**: P1 complete (connect, errors, disconnect). MVP deliverable.

---

## Phase 6: User Story 4 - Mantener la conexión válida y detectar cuándo reconectar (Priority: P2)

**Goal**: obtener credenciales válidas renovándolas sin login, persistir la renovación y
pasar a `reconnect_required` solo ante rechazos definitivos.

**Independent Test**: con `FakeGoogle`, caducar el access token y verificar: refresh
correcto y persistido. Después:

- `invalid_grant` → `reconnect_required`;
- un `5xx` → sigue `connected`;
- un secreto ausente → `reconnect_required`.

### Tests for User Story 4

- [X] T036 [P] [US4] Write `backend/tests/test_youtube_refresh.py`:
  - **`get_valid_credentials`** (direct call with a session and the app state):
    - with a token valid for > 60 s, it returns it without contacting Google;
    - with an expired token, it refreshes once, persists the new `access_token` and
      `expires_at` in the store (same `credential_ref`), and keeps the old refresh token
      unless the fake rotates it;
    - `invalid_grant` → row `reconnect_required` and `ConflictError("reconnect_required")`;
    - `5xx`/`429`/timeout → `AppError(503, "youtube_unavailable")`, row still `connected`;
    - a secret missing in the store → `reconnect_required`;
    - missing client file during the refresh → `503 oauth_not_configured`, status
      unchanged.
  - **`POST .../verify`**:
    - `connected` with the same channel → `200`, `last_verified_at` updated, and title,
      handle and thumbnail changes from the fake applied;
    - a different channel ID → `409 reconnect_required` and row `reconnect_required`;
    - channels `401` → one forced refresh and retry, then `reconnect_required` if it
      persists;
    - `403` → `reconnect_required`;
    - 2 channels → `reconnect_required`;
    - `not_connected` → `409 not_connected`;
    - Instagram → `409 platform_not_supported`;
    - allowed for an inactive account or project.
  - **Leaks**: add Verify cases to `backend/tests/test_youtube_secrets.py` (reusing
    `assert_no_secrets`), including a refresh that returns a new `FAKE_REFRESHED_ACCESS_TOKEN`:
    it never appears in the database, the verify response or the logs.
- [X] T037 [P] [US4] Add to `frontend/src/components/YouTubeConnectionPanel.test.tsx`:
  - a `reconnect_required` account shows the "Reconnect required" badge, the linked channel
    and **Reconnect** (not **Connect**);
  - **Reconnect guard** (from `reconnect_required`): with `oauth_configured: false`,
    clicking **Reconnect** calls neither `window.open` nor `authorizeYouTube` and shows the
    setup instructions; with `oauth_configured: true` and `authorizeYouTube` rejecting, the
    opened tab's `close()` is called and the error is shown;
  - **Verify connection** is shown only when `connected`;
  - a successful verify shows "Connection verified";
  - a `409 reconnect_required` response reloads the connection and shows the message;
  - `503 youtube_unavailable` shows the message and keeps "Connected".

### Implementation for User Story 4

- [X] T038 [US4] Implement
  `get_valid_credentials(session, store, gateway, account_id) -> TokenSet` in
  `backend/app/youtube_connections.py`:
  - a per-account `threading.Lock` (a dict guarded by a module lock);
  - 60 s margin;
  - refresh via `gateway.refresh` with the client config, persisting with
    `store.set(same_ref, ...)`;
  - error mapping per research §11/§14, with a helper
    `mark_reconnect_required(session, conn, reason)` that sets the status, updates
    `updated_at` and commits.

  It is the single entry point the future upload feature will reuse.
- [X] T039 [US4] Implement `POST /api/accounts/{account_id}/youtube-connection/verify` in
  `backend/app/youtube_connections.py`:
  1. `get_valid_credentials`;
  2. `list_my_channels`;
  3. on `GoogleUnauthorized`, refresh once and retry;
  4. outcome:
     - exactly one channel with the stored `channel_id` → update the public fields and
       `last_verified_at`, then `commit`;
     - otherwise (different ID, 0/2+ channels, repeated `401`, `403`) →
       `mark_reconnect_required` and `409 reconnect_required`;
     - `GoogleUnavailable` → `503` without a status change.
- [X] T040 [US4] In `frontend/src/components/YouTubeConnectionPanel.tsx`:
  - add **Verify connection** (`connected` only), calling `verifyYouTubeConnection` and
    showing "Connection verified" or the error;
  - render the `reconnect_required` state with **Reconnect**, reusing the Connect handler
    so it applies exactly the same protection: no tab when `oauth_configured === false`,
    and `tab?.close()` if `authorizeYouTube` fails before navigating the tab;
  - `reload()` after verify outcomes that change the status.

**Checkpoint**: la conexión se mantiene sola y degrada correctamente a `Reconnect required`.

---

## Phase 7: User Story 5 - Reconectar y proteger contra el canal equivocado (Priority: P2)

**Goal**: reconectar sustituye las credenciales del mismo canal. Un canal distinto exige una
confirmación explícita, y cancelar o caducar deja la conexión anterior intacta.

**Independent Test**: con fakes, reconectar con el mismo canal (nuevo `credential_ref`, el
antiguo borrado). Después reconectar con otro canal y comprobar:

- el intento queda `awaiting_confirmation` y la fila sin cambios;
- con `confirm` → canal nuevo;
- con `cancel` o caducidad → canal anterior intacto.

### Tests for User Story 5

- [X] T041 [P] [US5] Write `backend/tests/test_youtube_reconnect.py`:
  - **Reconnect after disconnect**: `connected` again; the URL still has
    `prompt=select_account consent` and `access_type=offline`.
  - **Same channel** from `connected` and from `reconnect_required`: a new
    `credential_ref`, the old secret deleted from the store, `status=connected` and
    `connected_at` updated.
  - **Different channel**:
    - the attempt is `awaiting_confirmation` with `current_channel`/`new_channel`
      (title + id), the row is unchanged and the store has only the old secret;
    - `confirm` → `completed`, row with the new channel and credentials, old secret
      deleted;
    - `cancel` → `cancelled`, row and store unchanged;
    - the registry clock advanced past `expires_at` before `confirm` → `GET` returns the
      attempt with status `expired`, `confirm` → `409 oauth_attempt_not_confirmable`, and
      the row and store are unchanged; after advancing the clock another 10 minutes past
      `finished_at`, `GET` → `404 oauth_attempt_not_found`.
  - **Confirm re-checks**:
    - `confirm` after the row was changed meanwhile (e.g. disconnected) →
      `409 connection_changed`;
    - `confirm` after the account was deactivated → `409 account_inactive`, attempt
      `failed`.
  - **Attempt state errors**: `confirm`/`cancel` on a `completed` attempt →
    `409 oauth_attempt_not_confirmable`; `cancel` on `cancelled` → `200` (idempotent);
    unknown id → `404 oauth_attempt_not_found`.
  - **No silent replacement**: no path changes `channel_id` without `confirm`.
- [X] T042 [P] [US5] Add to `frontend/src/components/YouTubeConnectionPanel.test.tsx`:
  - an attempt polled as `awaiting_confirmation` shows a warning with "Current channel"
    and "New channel" (titles and IDs) and the buttons **Replace with this channel** /
    **Keep current channel**;
  - **Replace** calls `confirmOAuthAttempt` and then reloads the connection;
  - **Keep** calls `cancelOAuthAttempt` and keeps the old channel displayed;
  - the warning names the AutoPublisher account (platform and `@handle`);
  - **Reconnect guard** (secondary action from `connected`): with
    `oauth_configured: false`, **Reconnect** calls neither `window.open` nor
    `authorizeYouTube` and shows the setup instructions; with `oauth_configured: true` and
    `authorizeYouTube` rejecting, the opened tab's `close()` is called.

### Implementation for User Story 5

- [X] T043 [US5] Extend the callback in `backend/app/youtube_connections.py`: when the
  account already has a row and the identified `channel_id` differs, call
  `registry.await_confirmation(attempt, new_channel, tokens)`, keeping the tokens only in
  memory. Respond with a `200` HTML page that tells the user to return to AutoPublisher to
  confirm. With the same channel, `complete_connection` (update path) runs as before.
- [X] T044 [US5] Implement `POST /api/youtube/oauth/attempts/{attempt_id}/confirm` and
  `/cancel` in `backend/app/youtube_connections.py`, per the contract:
  - **`confirm`**:
    1. requires `awaiting_confirmation`;
    2. re-checks that the account and project are active;
    3. re-checks that the current row's `channel_id` equals `attempt.current_channel.id`
       (`connection_changed`);
    4. checks the channel conflict;
    5. `complete_connection` with the pending tokens;
    6. `finish(completed)`.

    Any failure → `finish(failed)` and drops the pending tokens.
  - **`cancel`**: valid for `pending` or `awaiting_confirmation` → `finish(cancelled)` and
    drops the tokens, without revocation; idempotent on `cancelled`.
- [X] T045 [US5] Add the channel-change warning UI to
  `frontend/src/components/YouTubeConnectionPanel.tsx`:
  - a card showing the AutoPublisher account (platform, `@handle`, display name), plus
    "Current channel" and "New channel", each with title and `Channel ID`;
  - **Replace with this channel** → `confirmOAuthAttempt`, then `reload()`;
  - **Keep current channel** → `cancelOAuthAttempt`;
  - errors shown with `role="alert"`;
  - the **Reconnect** button stays available when `connected` as a secondary action, using
    the same handler as **Connect** (no tab when `oauth_configured === false`; close the
    tab if `authorizeYouTube` fails before navigating it).

**Checkpoint**: nunca se sustituye un canal sin confirmación explícita.

---

## Phase 8: User Story 6 - Evitar el mismo canal en dos cuentas del proyecto (Priority: P2)

**Goal**: un channel ID solo puede estar vinculado a una cuenta por proyecto (activa o
inactiva), con un mensaje que nombre la cuenta que ya lo tiene.

**Independent Test**: conectar `@CyberChannel` a `UC123` e intentar conectar otra cuenta del
mismo proyecto con `UC123`. Resultado esperado: `channel_already_connected`, nombrando
`@CyberChannel`, sin credenciales nuevas. En otro proyecto, permitido.

### Tests for User Story 6

- [X] T046 [P] [US6] Add to `backend/tests/test_youtube_reconnect.py` (or a new
  `backend/tests/test_youtube_channel_conflict.py`):
  - **Same project**: a second account in the same project gets `UC123` → attempt `failed`
    with `channel_already_connected`, whose message contains the other account's
    `@handle`; the store holds only the first secret and the second account stays
    `not_connected`.
  - **Inactive holder**: the holder account is inactive → still rejected.
  - **Other project**: an account in another project → `completed`.
  - **After disconnect**: once the holder is disconnected → `completed`.
  - **Replacement**: a channel-change `confirm` towards a channel owned by another account
    of the project → `409 channel_already_connected`.
  - **Race**: two prepared attempts for two accounts of the same project returning the
    same channel, completed in sequence through `complete_connection` with the code-level
    check bypassed (monkeypatch) → the second hits the unique index and is mapped to
    `channel_already_connected`, with its new secret deleted from the store.
- [X] T047 [P] [US6] Add to `frontend/src/components/YouTubeConnectionPanel.test.tsx`: an
  attempt that ends `failed` with `channel_already_connected` shows the message naming the
  other account.

### Implementation for User Story 6

- [X] T048 [US6] In `backend/app/youtube_connections.py`, add
  `ensure_channel_available(session, project_id, channel_id, account_id)`: it queries
  another row with the same `(project_id, channel_id)` and raises
  `ConflictError("channel_already_connected", "This YouTube channel is already connected to @<handle> in this project. Disconnect it there first.")`.
  Call it in the callback (before storing anything) and in `confirm`. In
  `complete_connection`, map an `IntegrityError` on
  `uq_youtube_connections_project_id_channel_id` to the same error, after the compensating
  `store.delete(new_ref)`.

**Checkpoint**: unicidad canal–proyecto garantizada en código y en base de datos.

---

## Phase 9: User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

**Goal**: las cuentas inactivas o de proyectos inactivos muestran su conexión, no permiten
iniciar ni completar autorizaciones y sí permiten desconectar.

**Independent Test**: desactivar una cuenta conectada y comprobar:

- muestra su estado y su canal;
- `authorize` → `409 account_inactive`;
- un callback pendiente se rechaza;
- `disconnect` funciona.

Repetir con el proyecto desactivado.

### Tests for User Story 7

- [X] T049 [P] [US7] Write `backend/tests/test_youtube_inactive.py`:
  - **`authorize`**: an inactive account → `409 account_inactive`; an inactive project →
    `409 project_inactive`. No attempt is created in either case.
  - **Callback**: already covered from US1 (T019). Here, add the `confirm` case: an
    `awaiting_confirmation` attempt whose project is deactivated before `confirm` →
    `409 project_inactive` and the old connection unchanged.
  - **Deactivation keeps the connection**: `PATCH /api/accounts/{id}`
    `{"is_active": false}` on a connected account keeps the row, the secret and
    `status=connected`; `GET .../youtube-connection` still works.
  - **Disconnect**: allowed while inactive (cross-check with T032).
- [X] T050 [P] [US7] Add to `frontend/src/components/YouTubeConnectionPanel.test.tsx`:
  - for an inactive account, and for an active account in an inactive project, the status
    and channel are shown;
  - **Connect**/**Reconnect** are disabled with the explanation "Reactivate the account
    (or project) to connect it.";
  - **Disconnect** stays enabled.

### Implementation for User Story 7

- [X] T051 [US7] In `backend/app/youtube_connections.py`, audit the use of
  `ensure_account_connectable` (created in T022): it must be called in `authorize` (T022),
  in the callback before the code exchange (T024) and in `confirm` (T044), and **never** in
  `disconnect`, `verify` or `GET`. Fix any gap revealed by T049.
- [X] T052 [US7] In `frontend/src/components/YouTubeConnectionPanel.tsx`, disable
  **Connect**/**Reconnect** with the explanatory text when `!account.is_active` or
  `!projectActive`, and keep **Disconnect** and the status display.

**Checkpoint**: todas las historias funcionan de forma independiente.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: documentación, endurecimiento de seguridad y validación final.

- [X] T053 [P] Update `README.md`:
  - **Status**: YouTube accounts can be connected via OAuth; nothing is uploaded yet.
  - **New section "Connecting YouTube"**:
    - the Google Cloud setup steps of quickstart §2 (enable YouTube Data API v3, External
      consent screen, test user, the two scopes, Desktop app client);
    - where to save the client JSON (`backend/data/google-oauth-client.json` or
      `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`) and that it must never be committed (no
      example file is provided);
    - `AUTOPUBLISHER_OAUTH_REDIRECT_URI` for non-default ports;
    - that the consent screen appears on every Connect/Reconnect on purpose
      (`prompt=consent`, to always get a refresh token);
    - that Disconnect only deletes local credentials and does not revoke Google access,
      how to remove access manually at myaccount.google.com/connections, and that this
      affects every AutoPublisher connection of that Google account.
  - **Secure storage**:
    - `keyring` is a new backend dependency;
    - requirements on Linux/Ubuntu: GNOME Keyring included in Ubuntu Desktop, otherwise
      `sudo apt install gnome-keyring`, or KWallet with Secret Service; a D-Bus session;
      an unlocked keyring;
    - optional `libsecret-tools`/`seahorse` for inspection;
    - the check command `uv run python -c "import keyring; print(keyring.get_keyring())"`;
    - that insecure or plaintext backends are refused, with no fallback, and that headless
      sessions are unsupported.
  - **Limitations**:
    - in Testing mode, refresh tokens expire after 7 days → Reconnect required;
    - an unverified app shows a warning;
    - uploads from unverified projects will be private (next feature).
  - **API routes**: list the new routes.
- [X] T054 Security review pass over `backend/app/youtube_*.py` and
  `backend/app/credential_store.py`:
  - grep for `logger.` and `print(` to confirm no token, code, verifier, client secret,
    response body or URL with query is logged;
  - confirm no `revoke` call exists (`grep -rn "revoke" backend/app` returns nothing
    functional);
  - confirm no fallback store exists;
  - confirm `__repr__`s are redacted;
  - confirm `.gitignore` covers the client file;
  - run `git status --short` with a real client file present in `backend/data/` to check it
    is not listed.
- [X] T055 Run the full quality suite and fix any issue: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` in `backend/`, and `npm test && npm run lint && npm run format:check && npm run typecheck && npm run build` in `frontend/`. Report any failing check explicitly.
- [X] T056 Manual validation with real Google following [quickstart.md](quickstart.md) §2–§6:
  - the full SC-001 flow, including the restart and the reconnect after Disconnect with the
    consent screen shown again;
  - **SC-002**: measure with a stopwatch the time from clicking the final grant button in
    Google until the account shows `Connected` in AutoPublisher. It must be **< 10 s**;
    record the measured value;
  - FR-017: the AutoPublisher account's handle and display name are unchanged after
    connecting;
  - the error cases, the locked keyring and the missing Secret Service;
  - wrong channel and duplicate channel;
  - the multi-channel Google account check if one is available, otherwise record that §6
    was not run.

  Record the results and any deviation in the PR description.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. T002 before any backend code.
- **Foundational (Phase 2)**: depends on Setup and blocks every story. Internal order:
  1. T004 → T005;
  2. T006–T009 tests in parallel;
  3. T010 → T011;
  4. T012/T013/T014 in parallel;
  5. T015 → T016 → T017;
  6. T018 in parallel with the backend work.
- **US1 (Phase 3)**: after Foundational.
- **US2 (Phase 4)**: after US1 (hardens the callback written in T024).
- **US3 (Phase 5)**: after Foundational. Its tests need a connected account, so in practice
  it comes after US1.
- **US4 (Phase 6)**: after US1 (needs a stored connection).
- **US5 (Phase 7)**: after US1. The cross-checks of T041 use the disconnect route from US3.
- **US6 (Phase 8)**: after US1. T046's `confirm` case needs US5.
- **US7 (Phase 9)**: after US1. Its disconnect cross-check needs US3 and its `confirm` case
  needs US5. The inactive checks in `authorize` and in the callback already exist since US1
  (T022, T024); US7 adds the dedicated suite, the audit (T051) and the UI.
- **Polish (Phase 10)**: after all the desired stories.

### Within Each User Story

- Tests first; they must fail.
- Backend implementation, then frontend.
- Run `uv run pytest` / `npm test` at each checkpoint.

### Parallel Opportunities

- Setup: T003 in parallel with T002.
- Foundational:
  - T006, T007, T008 and T009 (different test files);
  - T012, T013 and T014 (different modules);
  - T018 (frontend) in parallel with all backend foundational work.
- Within each story: the backend test task and the frontend test task are `[P]`, and the
  frontend implementation can proceed in parallel with the backend implementation once the
  API contract is fixed.
- After US1: US3, US4, US5 and US7 touch different areas of `youtube_connections.py`. Run
  them sequentially to avoid conflicts in that file, but their frontend and test parts can
  overlap.

---

## Parallel Example: Foundational

```bash
Task: "Write backend/tests/test_youtube_oauth.py (T006)"
Task: "Write backend/tests/test_credential_store.py (T007)"
Task: "Write backend/tests/test_youtube_gateway.py (T008)"
Task: "Extend backend/tests/test_migrations.py (T009)"

Task: "Implement backend/app/credential_store.py (T012)"
Task: "Implement backend/app/youtube_oauth.py (T013)"
Task: "Implement backend/app/youtube_gateway.py (T014)"
Task: "Frontend types, api and fake api (T018)"
```

## Parallel Example: User Story 1

```bash
Task: "Write backend/tests/test_youtube_connect.py happy path (T019)"
Task: "Write backend/tests/test_youtube_secrets.py (T020)"
Task: "Extend backend/tests/test_persistence.py (T021)"
Task: "Create frontend/src/components/YouTubeConnectionPanel.tsx (T025)"
Task: "Write frontend/src/components/YouTubeConnectionPanel.test.tsx (T027)"
```

---

## Implementation Strategy

### MVP First (P1: US1 + US2 + US3)

1. Phase 1 + Phase 2.
2. US1 → validate with fakes, then quickstart §3 steps 1–7 with real Google.
3. US2 → every error is visible and leaves no credentials behind.
4. US3 → disconnect deletes the local secrets.
5. **STOP and VALIDATE**: connect, restart, disconnect and connect again work for real.

### Incremental Delivery

1. MVP (P1).
2. US4: refresh and verify (the connection stays useful over time).
3. US5: reconnect plus wrong-channel protection.
4. US6: duplicate channel per project.
5. US7: inactive rules.
6. Polish: README, security review, full checks, quickstart.

Commit after each task or logical group, with small commits in English, for example:

- `feat(backend): add secure credential store with keyring allow-list`;
- `feat(backend): add YouTube OAuth connect flow with PKCE`;
- `feat(frontend): add YouTube connection panel`;
- `test(backend): cover YouTube refresh and reconnect`;
- `docs: document connecting YouTube`.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- Out of scope; never implement in this feature:
  - `videos.insert`/uploads;
  - publishing a Publication;
  - the scheduler;
  - `PublicationAttempt`;
  - retries;
  - analytics;
  - remote video editing;
  - thumbnails, playlists and comments;
  - OAuth for other platforms;
  - token revocation;
  - any fallback secret storage.
- Never commit `backend/data/`, the real client JSON, tokens, or a `.env`.
