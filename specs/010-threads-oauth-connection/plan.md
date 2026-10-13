# Implementation Plan: Conexión de cuentas reales de Threads mediante OAuth oficial

**Branch**: `010-threads-oauth-connection` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-threads-oauth-connection/spec.md`

## Summary

Vincular una `Account` de plataforma Threads con una cuenta real de Threads mediante la
**Threads API** oficial. El backend genera la URL de autorización de Threads
(`threads_basic`, `threads_content_publish`, `state` de un solo uso). Como Meta exige un
redirect URI **HTTPS**, se reutiliza el patrón de la Feature 008: el usuario pega en
AutoPublisher la redirect URL de `https://localhost/...` y el endpoint `complete` la valida
**componente a componente** (scheme, hostname, puerto efectivo y path exactos). El backend
intercambia el código por un token corto y después por uno **largo (60 días)**, confirma los
permisos con **`debug_token`** autenticado con la propia credencial del usuario-tester (único
mecanismo documentado; el intercambio no devuelve permisos) y consulta `/me` para la identidad
(`id`, username, nombre, foto). Los tres `user_id` deben coincidir.

El token largo se guarda solo en el keyring (servicio `autopublisher.threads`) junto con
`token_obtained_at` y `expires_at`; ese secreto es la fuente de verdad y SQLite solo refleja
identidad pública, estado, referencia opaca y fechas (reparables desde el secreto si quedan
desfasadas). Política de renovación (`th_refresh_token`), solo cuando AutoPublisher necesita la
credencial: con más de 7 días restantes no se renueva; con 7 días o menos y ≥ 24 h de
antigüedad (condición de Meta) se renueva; un fallo temporal con token vigente conserva el
actual. Sin scheduler ni renovación periódica. Estados, Verify, Disconnect
local, confirmación ante cambio de cuenta, unicidad por proyecto, reglas de inactivos y
redacción de logs replican los patrones de las Features 005/008 en módulos `threads_*`
independientes de Instagram. Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring` (existentes).
**Sin dependencias nuevas.**

**Storage**: SQLite (tabla nueva `threads_connections`, migración `0009`); keyring del sistema
operativo (servicio `autopublisher.threads`); archivo local no versionado
`backend/data/threads-app.json`.

**Testing**: pytest con `FakeThreads` (`httpx.MockTransport`) e `InMemoryCredentialStore`;
Vitest + Testing Library con `FakeApi`. Todo sin Internet, sin Meta y sin keyring real.

**Target Platform**: aplicación local (Linux principal; macOS/Windows vía backends de keyring
permitidos) con navegador en la misma máquina.

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: `Connected` en menos de 10 s tras enviar la URL pegada (SC-002): cuatro
llamadas a Meta con timeout de 10 s cada una (`META_TIMEOUT_SECONDS` existente).

**Constraints**: redirect URI HTTPS (Meta); sin PKCE (no documentado); código de 1 h y un solo
uso; cero secretos fuera del keyring; sin revocación remota; sin lógica de Threads en
scheduler/publishing; tests sin red.

**Scale/Scope**: un usuario y pocas cuentas; 7 rutas nuevas, 1 tabla, 1 panel.

No queda ningún NEEDS CLARIFICATION: endpoints, hosts, versión, redirect URI, PKCE, tokens,
renovación, caducidades, permisos efectivos, callbacks de Meta, revocación y App Review están
resueltos en [research.md](research.md). Lo que la documentación no garantiza se valida en el
quickstart con condiciones de detención (A: redirect URI, B: callbacks de Meta, F:
`debug_token`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin dependencias ni infraestructura nueva; flujo de pegado en vez de TLS local o túneles; sin renovación en segundo plano; sin publisher de Threads; sin App Access Token; sin refactorizar Instagram/YouTube (registro de intentos propio). | ✅ |
| II. Spec-Driven | Plan derivado de `spec.md` (FR-001…FR-054) incluidos los cuatro ajustes de la revisión; desviaciones de protocolo documentadas en research. | ✅ |
| III. Arquitectura modular | Módulos `threads_oauth.py`, `threads_gateway.py`, `threads_connections.py`. `accounts.py`, `AccountRead`, `publishing.py`, `publications.py`, `scheduler.py`, `automation.py` y los módulos de Instagram no cambian. Tests de arquitectura ampliados a Threads. Único punto de contacto en el frontend: la condición por plataforma de `AccountList`. | ✅ |
| IV. Seguridad | Token solo en el keyring, sin fallback; app secret en archivo ignorado por Git; `state` de un solo uso; URL pegada solo en el cuerpo de un POST y validada por componentes; redacción de `access_token`, `input_token`, `client_secret`, `code`, `state`, `Bearer` y `TH|`; API oficial. | ✅ |
| V. Calidad | Tests de todos los casos de FR-053 con fakes; lint, formato, mypy, typecheck y build en el quickstart; ningún fallo deja estados silenciosos. | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés; README + `docs/threads-accounts.md`. | ✅ |

**Re-check post-diseño**: sin violaciones. No se necesita Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/010-threads-oauth-connection/
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
│   ├── config.py                  # + get_threads_app_file(), THREADS_ATTEMPT_TTL/RETENTION
│   ├── credential_store.py        # + THREADS_SERVICE = "autopublisher.threads" (sin cambios de lógica)
│   ├── models.py                  # + ThreadsConnection, ThreadsConnectionStatus
│   ├── schemas.py                 # + ThreadsIdentityRead, ThreadsConnectionRead, ThreadsAuthorizeRead,
│   │                              #   ThreadsOAuthAttemptRead, ThreadsCompleteWrite
│   ├── threads_oauth.py           # NEW: ThreadsAppConfig, authorization URL, strict redirect URL
│   │                              #   parsing, ThreadsIdentity, ThreadsAttemptRegistry (memoria)
│   ├── threads_gateway.py         # NEW: code exchange, long-lived exchange, refresh, debug_token,
│   │                              #   /me, ThreadsToken, clasificación de errores; host/versión
│   ├── threads_connections.py     # NEW: router, reglas, complete/confirm/cancel, verify, disconnect,
│   │                              #   get_valid_credentials, get_linked_identity, RedactThreadsSecrets
│   └── main.py                    # + router, registry, gateway, threads_credential_store,
│                                  #   threads_transport (inyectable); sin publisher de Threads
├── migrations/versions/
│   └── 0009_create_threads_connections.py
└── tests/
    ├── fakes.py                   # + FakeThreads
    ├── conftest.py                # + fixtures fake_threads / threads store / threads app file
    ├── test_accounts.py           # arquitectura: núcleo de Accounts sin "threads"
    ├── test_publications_states.py# arquitectura: publishing/publications/scheduler/automation sin threads_
    ├── test_migrations.py         # + 0009
    ├── test_threads_oauth.py      # config, URL, parsing estricto de la redirect URL, registry
    ├── test_threads_gateway.py    # endpoints, parsing, debug_token, clasificación de errores
    ├── test_threads_connect.py    # happy path, permisos, user_id incoherente, unicidad, concurrencia
    ├── test_threads_reconnect.py  # misma cuenta, cambio confirmado/cancelado/caducado
    ├── test_threads_tokens.py     # ventana de 7 días, condición 24 h, temporales vs definitivos,
    │                              #   secreto renovado + commit SQLite fallido → reparación idempotente
    ├── test_threads_verify.py     # identidad, mismatch, permiso retirado, datos cambiados, inactivos
    ├── test_threads_disconnect.py # idempotencia, store no disponible, sin llamadas a Meta
    ├── test_threads_inactive.py   # cuentas/proyectos inactivos
    └── test_threads_secrets.py    # SQLite, logs, respuestas, errores sin secretos

frontend/src/
├── types.ts                       # + ThreadsConnection, ThreadsIdentity, ThreadsOAuthAttempt
├── api.ts                         # + funciones threads-connection / threads oauth
├── test-fake-api.ts               # + soporte Threads
├── components/
│   ├── AccountList.tsx            # + condición platform === "threads"
│   ├── ThreadsConnectionPanel.tsx # NEW
│   └── ThreadsConnectionPanel.test.tsx # NEW
└── storage-safety.test.tsx        # sin cambios; cubre los archivos nuevos

docs/threads-accounts.md           # NEW: caso de uso, tester, redirect URI, callbacks, revocación manual
README.md                          # + "Connecting Threads"
.gitignore                         # + threads-app*.json
```

**Structure Decision**: misma estructura web y mismo patrón de módulos por plataforma que las
Features 005 y 008. Modelos y schemas de Threads se añaden a `models.py`/`schemas.py` junto a
los de otras plataformas, sin tocar `Account`/`AccountRead`.

## Diseño por capas

### `threads_oauth.py` (puro, sin red)

- `ThreadsAppConfig(app_id, app_secret[repr=False], redirect_uri)`;
  `load_threads_app_config(path)` → `ThreadsOAuthNotConfigured` si falta o es inválido
  (`redirect_uri` https, con host, sin userinfo, query ni fragment).
- `SCOPES = ("threads_basic", "threads_content_publish")`, `REQUIRED_SCOPES = frozenset(SCOPES)`.
- `build_authorization_url(config, state)`: solo parámetros documentados.
- `parse_redirect_url(pasted, config) -> RedirectResult(state, code | None, error | None)`:
  algoritmo de research §4 (sin `startswith`, sin tolerar barra final, sin userinfo,
  parámetros duplicados rechazados, `#_` ignorado).
- `ThreadsIdentity(threads_user_id, username, display_name, profile_picture_url)` con `to_read`.
- `ThreadsAttemptRegistry` con la misma interfaz que el de Instagram (`create`,
  `consume_state`, `get`, `finish`, `await_confirmation`, `claim_confirmation`, `cancel`,
  `expire_for_account`).

### `threads_gateway.py` (solo red)

- Constantes: `THREADS_GRAPH_HOST`, `THREADS_API_VERSION = "v1.0"`, endpoints de research §2.
- `ShortLivedToken(access_token[repr=False], user_id)`.
- `ThreadsToken(access_token[repr=False], token_obtained_at, expires_at, scopes)` con
  `to_json`/`from_json` (zona horaria obligatoria).
- `ThreadsTokenInfo(is_valid, user_id, scopes, data_access_expires_at)`.
- `exchange_code(code, config)` (POST, cuerpo de formulario), `exchange_long_lived(short, config)`,
  `refresh(token)`, `debug_token(access_token)` (`input_token` = `access_token`),
  `fetch_me(access_token)`. `token_obtained_at = clock()` al recibir la respuesta;
  `expires_at = token_obtained_at + expires_in`.
- Excepciones: `ThreadsUnavailable`, `ThreadsTokenInvalid`, `ThreadsPermissionDenied`,
  `ThreadsRejected`, `ThreadsUnexpectedResponse` (research §10). Nunca llevan cuerpo, URL ni
  token; se lanzan `from None`.

### `threads_connections.py` (reglas y rutas)

- Lookups: `get_threads_account_or_error`, `get_connection`, `oauth_configured`, `load_config`.
- Reglas: `ensure_account_connectable`, `ensure_identity_available`, `complete_connection`
  con orden seguro (data-model): secreto con `credential_ref` **nueva** → commit de la fila →
  solo entonces borrar la referencia anterior; cualquier fallo del commit hace rollback, borra el
  secreto nuevo y deja intacta la conexión anterior; `IntegrityError` →
  `threads_account_already_connected`.
- `_confirm_grant(gateway, access_token, expected_user_id)`: `debug_token` → `is_valid`, `user_id`,
  scopes (FR-008); compartida por `complete` y `verify`.
- Ciclo de vida: `get_valid_credentials` con candado por cuenta y la política de
  data-model: `RENEWAL_WINDOW = 7 días` (constante interna, decisión de producto),
  `REFRESH_MIN_AGE = 24 h` (condición de Meta), `EXPIRY_MARGIN = 5 min`.
- Consistencia: el secreto es autoritativo. `_sync_metadata(connection, token)` copia
  `token_obtained_at`/`expires_at` del secreto a SQLite si difieren (idempotente) al inicio de
  cada acceso a la credencial. Tras una renovación correcta, si falla el commit de SQLite, no se
  restaura el token antiguo, se registra un aviso y se devuelve el token nuevo. El `GET` solo lee
  el secreto cuando SQLite indica caducidad, para no marcar `reconnect_required` por metadata
  desfasada.
- Inspección tras renovar (data-model 8c): `debug_token` sobre el token nuevo; éxito →
  `scopes` (solo si cambian) y `data_access_expires_at` oficiales; señal definitiva →
  `reconnect_required`; fallo temporal → se conserva el token nuevo y la última metadata.
- `data_access_expires_at` es solo informativo: nunca provoca `reconnect_required` por sí solo
  (ni en el `GET` ni en `get_valid_credentials`) y nunca se calcula sumando 90 días.
- Verify reescribe el secreto solo si los scopes confirmados cambian, conservando token y
  fechas; un fallo de esa escritura → `credential_store_unavailable` sin cambio de estado.
- `mark_reconnect_required`.
- `verify_identity` y `get_linked_identity` para la Feature 011.
- `RedactThreadsSecrets` instalado en `HTTP_LOGGERS` desde `create_app`.
- Errores con `AppError(status, "threads_…", message)`; genéricos existentes para
  `not_found`, `platform_not_supported`, `project_inactive`, `account_inactive`,
  `credential_store_unavailable`.
- Sin `ensure_not_publishing`: no hay publicación de Threads (se añadirá en la Feature 011).

### Frontend

- `ThreadsConnectionPanel`: estados y acciones de spec FR-049; flujo *Connect → abrir pestaña →
  pegar la redirect URL → Complete connection* (campo vaciado y URL descartada tras enviar);
  advertencia de cambio de cuenta (Replace / Cancel); caducidades conocidas; mensaje de
  revocación manual tras Disconnect; respeto de inactivos. Errores mostrados por `code` y
  `message` seguros.
- Nada en el almacenamiento del navegador.

## Tests obligatorios de renovación y consistencia (`test_threads_tokens.py`)

Con `FakeThreads`, `InMemoryCredentialStore` y reloj falso:

1. Token vigente con > 7 días restantes y ≥ 24 h de antigüedad → se usa sin llamar a
   `refresh_access_token`.
2. ≤ 7 días restantes y ≥ 24 h → se renueva; secreto y SQLite con nuevo `token_obtained_at` y
   `credential_expires_at = now + expires_in`.
3. ≤ 7 días restantes y < 24 h → se usa sin renovar mientras sea vigente.
4. Renovación con fallo temporal (red, 5xx, 429, respuesta inesperada) y token vigente → se
   devuelve el token actual, estado `connected`, sin cambios en el secreto.
5. Renovación con fallo temporal y token dentro de `EXPIRY_MARGIN` → `threads_unavailable`,
   sin cambio de estado.
6. Token caducado → `reconnect_required` sin llamar a Meta.
7. Renovación con 190 / permiso denegado / rechazo → `reconnect_required`.
8. **Secreto renovado + commit SQLite fallido** (fallo inyectado en el commit tras
   `store.set`): la llamada devuelve el token nuevo; el secreto contiene el token nuevo (no se
   restaura el antiguo); SQLite conserva la metadata antigua; el estado sigue `connected`.
9. **Siguiente acceso tras (8)**: lee el secreto, repara `token_obtained_at` y
   `credential_expires_at` en SQLite y **no** vuelve a llamar a `refresh_access_token`.
10. **Reparación idempotente**: dos accesos seguidos tras (8) dejan la misma metadata y un solo
    `UPDATE` efectivo; sin renovaciones adicionales.
11. **`GET` con metadata SQLite caducada pero secreto renovado vigente**: repara SQLite y sigue
    `connected` sin llamar a Meta; con el almacén no disponible no cambia el estado; con el
    secreto también caducado → `reconnect_required`.
12. Renovaciones concurrentes de la misma cuenta → una sola llamada a Meta (candado).
13. **`data_access_expires_at` antiguo + renovación correcta**: SQLite tiene un
    `data_access_expires_at` en el pasado; el token entra en la ventana y se renueva; el
    `debug_token` posterior devuelve `is_valid=true` y una fecha futura → SQLite queda con la
    fecha oficial nueva y la conexión **nunca** pasa a `reconnect_required` (tampoco en `GET`
    antes ni después de la renovación).
14. **Inspección tras renovar con fallo temporal**: renovación correcta y `debug_token` con
    error temporal → se devuelve el token nuevo, el secreto lo conserva (no se restaura el
    antiguo), `scopes` y `data_access_expires_at` mantienen el último valor conocido, estado
    `connected`.
15. **Inspección tras renovar con señal definitiva** (`is_valid=false`, permiso ausente o
    `user_id` distinto) → `reconnect_required`.

Tests de orden seguro (FR-029) en otros archivos: primera conexión con commit fallido tras
guardar el secreto (T027, `test_threads_connect.py`) y reconexión/confirmación con commit
fallido (T045, `test_threads_reconnect.py`).

## Riesgos y validaciones bloqueantes

| Riesgo | Mitigación |
|---|---|
| Meta rechaza `https://localhost/...` como redirect URI de Threads | Quickstart A; detener y replantear (research §3). |
| Meta exige Deauthorize/Data Deletion URLs públicas y funcionales | AutoPublisher no implementa esos callbacks; quickstart B intenta configurar sin ellas; si Meta las exige, detener y revisar arquitectura; nunca valores ficticios, túneles ni workarounds (research §12). |
| `debug_token` no acepta la credencial del tester o no devuelve `scopes` | Quickstart F; detener y revisar research §7; FR-008 no se relaja. |
| Host `graph.threads.net` vs `.com` | Constante única; quickstart E. |
| Token caduca por falta de uso en su ventana final de 7 días, o concesión vencida (90 días / perfil privado) | Caducidades visibles en la interfaz; Verify dentro de la ventana renueva; `Reconnect required` solo con señal oficial (`is_valid=false`, 190, permiso ausente) o token caducado. |
| `data_access_expires_at` desfasado tras una renovación que extendió la concesión | Inspección con `debug_token` tras renovar; la fecha local es solo informativa y nunca rompe una conexión por sí sola. |
| Fallo de persistencia tras guardar un secreto al conectar o reconectar | `credential_ref` nueva por conexión; commit antes de borrar la anterior; rollback + borrado del secreto nuevo; conexión anterior intacta. |
| Renovación guardada en el keyring pero commit SQLite fallido | Secreto autoritativo; reparación idempotente en el siguiente acceso; nunca se restaura el token antiguo ni se vuelve a renovar por metadata desfasada. |
| Duplicación del registro de intentos con Instagram | Aceptada para no ampliar alcance; candidato a refactor futuro. |

## Complexity Tracking

Sin violaciones de la Constitution.
