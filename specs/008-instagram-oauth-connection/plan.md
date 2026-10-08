# Implementation Plan: Conexión de cuentas reales de Instagram mediante Instagram Login

**Branch**: `008-instagram-oauth-connection` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-instagram-oauth-connection/spec.md`

## Summary

Vincular una `Account` de plataforma Instagram con una cuenta Instagram Professional
(Business o Creator) mediante **Instagram API with Instagram Login**. El backend genera la URL
oficial de autorización con `state` de un solo uso. Como Meta exige un redirect URI **HTTPS**,
no hay un servidor HTTPS de callback: el usuario copia del navegador la redirect URL a la que
Instagram le lleva (`https://localhost/...`, donde no escucha nada), la pega en AutoPublisher
y la envía al endpoint `complete`, que devuelve el resultado de forma síncrona. El backend valida el `state`, intercambia el
código por un token corto y después por uno **largo (60 días)**, verifica los permisos con el
campo `permissions` de la respuesta y consulta `/me` para obtener la identidad Professional
(`user_id`, username, tipo, foto).

El token largo se guarda solo en el keyring, con el servicio `autopublisher.instagram` y la
infraestructura de `credential_store.py`. SQLite guarda únicamente la identidad pública, el
estado, la referencia opaca y las fechas. La renovación usa `ig_refresh_token` (token con
≥ 24 h de antigüedad y vigente), con su propia política. El resto replica los patrones de la
Feature 005: estados, Verify, Disconnect sin revocación remota, confirmación ante cambio de
cuenta, unicidad por proyecto respaldada por constraint, reglas de inactivos y redacción de
logs, en módulos aislados de la plataforma. Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring` (existentes).
**Sin dependencias nuevas.**

**Storage**: SQLite (nueva tabla `instagram_connections`, migración `0007`); keyring del
sistema operativo para el token (servicio `autopublisher.instagram`); archivo local no
versionado `backend/data/instagram-app.json` para la Meta App.

**Testing**: pytest con un fake de Meta (`FakeMeta`, `httpx.MockTransport`) e
`InMemoryCredentialStore`; Vitest + Testing Library con `FakeApi`. Todo sin Internet ni keyring
real.

**Target Platform**: aplicación local (Linux principal; macOS/Windows vía backends de keyring
permitidos) con navegador en la misma máquina.

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: conexión visible en menos de 10 s tras pegar la URL (SC-002);
timeouts HTTP de 10 s hacia Meta.

**Constraints**: redirect URI HTTPS obligatorio (Meta); sin PKCE (no documentado); cero
secretos fuera del keyring; sin revocación remota; tests sin red.

**Scale/Scope**: un usuario y pocas cuentas; 7 rutas nuevas y 1 panel nuevo.

Todas las incógnitas del spec (endpoints, redirect URI, PKCE, tokens, refresh, caducidades,
versión de Graph API, permisos efectivos, revocación, App Review) quedan resueltas en
[research.md](research.md). No queda ningún NEEDS CLARIFICATION. Los puntos que la
documentación no cubre se validan explícitamente en el quickstart (A–D).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin dependencias ni infraestructura nueva: flujo de pegado en vez de TLS local o túneles. Sin refresco en segundo plano. Sin publicación. Registro de intentos propio en lugar de refactorizar YouTube (no amplía el alcance). | ✅ |
| II. Spec-Driven | Plan derivado de `spec.md` (FR-001…FR-052); las desviaciones de protocolo se documentan en research. | ✅ |
| III. Arquitectura modular | Módulos `instagram_oauth.py`, `instagram_gateway.py` e `instagram_connections.py`. `accounts.py` y `AccountRead` no cambian. Test de arquitectura ampliado a Instagram. El único punto de contacto en el frontend es la condición por plataforma ya existente en `AccountList`. | ✅ |
| IV. Seguridad | Token solo en el keyring, sin fallback. App secret en archivo local ignorado por Git. `state` de un solo uso. URL pegada solo en el cuerpo de un POST. Redacción de `access_token`/`client_secret`/`code`/`state` en logs HTTP. API oficial, sin scraping. | ✅ |
| V. Calidad | Tests de todos los casos de FR-051 con fakes. Lint, formato, mypy, typecheck y build en el quickstart. Ningún fallo deja estados silenciosos. | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés. README + `docs/instagram-accounts.md` actualizados. | ✅ |

**Re-check post-diseño**: sin violaciones. No se necesita Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/008-instagram-oauth-connection/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py                    # + get_instagram_app_file(), INSTAGRAM_* TTLs
│   ├── credential_store.py          # + INSTAGRAM_SERVICE constant (sin cambios de lógica)
│   ├── models.py                    # + InstagramConnection, InstagramConnectionStatus, InstagramAccountType
│   ├── schemas.py                   # + InstagramIdentityRead, InstagramConnectionRead,
│   │                                #   InstagramAuthorizeRead, InstagramOAuthAttemptRead, InstagramCompleteWrite
│   ├── instagram_oauth.py           # NEW: Meta App config, authorization URL, pasted redirect URL parsing,
│   │                                #   InstagramAttemptRegistry (memoria)
│   ├── instagram_gateway.py         # NEW: token exchange, long-lived exchange, refresh, /me,
│   │                                #   clasificación de errores Meta; GRAPH_API_VERSION
│   ├── instagram_connections.py     # NEW: router, reglas, complete/confirm/cancel, verify,
│   │                                #   disconnect, get_valid_credentials, log redaction
│   └── main.py                      # + router, registry, gateway, instagram_credential_store,
│                                    #   instagram_transport (inyectable en tests)
├── migrations/versions/
│   └── 0007_create_instagram_connections.py
└── tests/
    ├── fakes.py                     # + FakeMeta
    ├── conftest.py                  # + fixtures fake_meta / instagram store
    ├── test_accounts.py             # arquitectura: núcleo sin "instagram"
    ├── test_instagram_oauth.py      # URL, config, parsing de redirect, registry
    ├── test_instagram_gateway.py    # endpoints, parsing, clasificación de errores
    ├── test_instagram_connect.py    # flujo completo, Business/Creator, no profesional, permisos, unicidad
    ├── test_instagram_reconnect.py  # misma cuenta, cambio con confirmación/cancelación
    ├── test_instagram_tokens.py     # ciclo de vida, refresh, temporales vs definitivos
    ├── test_instagram_verify.py     # identidad, mismatch, cambios públicos
    ├── test_instagram_disconnect.py # idempotencia, store no disponible
    ├── test_instagram_inactive.py   # cuentas/proyectos inactivos
    └── test_instagram_secrets.py    # SQLite, logs, respuestas sin secretos

frontend/src/
├── types.ts                         # + InstagramConnection, InstagramIdentity, InstagramOAuthAttempt
├── api.ts                           # + funciones instagram-connection / instagram oauth
├── test-fake-api.ts                 # + soporte Instagram
├── components/
│   ├── AccountList.tsx              # + condición platform === "instagram"
│   ├── InstagramConnectionPanel.tsx # NEW
│   └── InstagramConnectionPanel.test.tsx # NEW
└── storage-safety.test.tsx          # (sin cambios; sigue cubriendo los nuevos archivos)

docs/instagram-accounts.md           # NEW: Meta App, tester, redirect URI, App Review, revocación manual
README.md                            # + "Connecting Instagram"
.gitignore                           # + instagram-app*.json, meta-app*.json
```

**Structure Decision**: misma estructura web (backend/frontend) y los mismos patrones de
módulo por plataforma que la Feature 005. Los modelos y schemas de Instagram se añaden a
`models.py`/`schemas.py` como los de YouTube, sin tocar `Account`/`AccountRead`.

## Diseño por capas

### `instagram_oauth.py` (puro, sin red)

- `MetaAppConfig(app_id, app_secret[repr=False], redirect_uri)`; `load_meta_app_config(path)`
  → `InstagramOAuthNotConfigured` si falta o es inválido (https obligatorio).
- `SCOPES = ("instagram_business_basic", "instagram_business_content_publish")`.
- `build_authorization_url(config, state)` con `force_reauth=true`.
- `parse_redirect_url(pasted, config) -> RedirectResult(state, code | None, error | None)`:
  compara esquema/host/puerto/ruta con el redirect URI (tolera una barra final), ignora el
  fragmento `#_` y elimina un `#_` residual del código.
- `InstagramIdentity(instagram_user_id, app_scoped_id, username, account_type, profile_picture_url)`.
- `InstagramAttemptRegistry`: `create`, `consume_state(attempt_id, state)` (tiempo constante;
  un `state` distinto no consume), `get`, `finish`, `await_confirmation`,
  `claim_confirmation`, `cancel`, `expire_for_account`. TTL y retención de 10 min.

### `instagram_gateway.py` (solo red)

- `InstagramToken(access_token[repr=False], issued_at, expires_at, permissions)` con
  `to_json`/`from_json`.
- `exchange_code(code, config) -> ShortLivedToken(access_token, permissions)`.
- `exchange_long_lived(short_token, config) -> InstagramToken`.
- `refresh(token) -> InstagramToken`.
- `fetch_me(access_token) -> InstagramIdentity` (`GRAPH_API_VERSION = "v26.0"`, solo para endpoints versionados).
- Excepciones: `MetaUnavailable`, `MetaTokenInvalid`, `MetaPermissionDenied`, `MetaRejected`,
  `MetaUnexpectedResponse` (tabla en research §9). Nunca incluyen cuerpo, URL ni token.
  `MetaPermissionDenied` lleva, si Meta lo indica de forma segura, el nombre del permiso
  afectado (solo si es uno de los dos requeridos).

### `instagram_connections.py` (reglas y rutas)

- Lookups: `get_instagram_account_or_error`, `get_connection`, `oauth_configured`.
- Reglas: `ensure_account_connectable`, `ensure_identity_available` (unicidad por proyecto),
  `complete_connection` (guardar secreto → fila → borrar secreto anterior; rollback borra el
  secreto nuevo; `IntegrityError` → `instagram_account_already_connected`).
- Ciclo de vida: `get_valid_credentials(session, store, gateway, account_id)` (política de
  data-model; el reloj es el del gateway) con candado por cuenta;
  `mark_reconnect_required`.
- `verify_identity` (compartida por la ruta y por la futura Feature 009): solo sobre
  `connected` con `Account` y proyecto activos; comprueba identidad, tipo Professional y
  permisos (la clasificación "permiso ausente/retirado" llega del gateway como
  `MetaPermissionDenied`, con el permiso afectado si Meta lo indica de forma segura) y pasa a
  `reconnect_required` con `instagram_reconnect_required` cuando falta un permiso.
- Log redaction: `RedactInstagramSecrets` instalado en `HTTP_LOGGERS` junto al filtro de
  YouTube (`install_log_redaction()` se llama desde `create_app`).
- Errores con `AppError(status, "instagram_…", message)` para no ampliar el `ConflictCode` común
  salvo los códigos genéricos ya existentes (`platform_not_supported`, `project_inactive`,
  `account_inactive`).
- Sin `ensure_not_publishing`: aún no existe publicación de Instagram (se añadirá en 009).

### Frontend

- `InstagramConnectionPanel` con los estados y acciones de FR-044, el flujo
  *Connect → abrir pestaña → pegar la redirect URL → Complete connection* (el campo se vacía y
  la URL se descarta tras enviarla), advertencia de cambio de
  cuenta (Replace / Cancel), caducidad del acceso, mensaje de revocación manual tras
  Disconnect y respeto de inactivos (`Connect`, `Reconnect` y `Verify connection` bloqueados;
  `Verify connection` solo en `Connected`).
- No guarda nada en el navegador; vacía el campo pegado tras enviarlo.

## Riesgos y validaciones bloqueantes

| Riesgo | Mitigación |
|---|---|
| Meta rechaza `https://localhost/...` como redirect URI | Quickstart A; detener y replantear (p. ej. listener HTTPS local). |
| Permisos que requieren App Review incluso para la cuenta tester | Quickstart B; documentar y detener. |
| La respuesta del intercambio no trae `permissions` o cambia de forma | Quickstart D; parser tolerante con la forma con y sin `data`; si falta → no se conecta. |
| Token caduca por falta de uso (60 días) | Se muestra la caducidad; Verify renueva; `Reconnect required` claro. |

## Complexity Tracking

Sin violaciones de la Constitution.
