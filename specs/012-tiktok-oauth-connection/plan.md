# Implementation Plan: Conexión de cuentas reales de TikTok mediante OAuth oficial (Login Kit for Desktop)

**Branch**: `012-tiktok-oauth-connection` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/012-tiktok-oauth-connection/spec.md`

## Summary

Vincular una `Account` de plataforma TikTok con una cuenta real mediante **TikTok Login Kit for
Desktop** (OAuth v2). El backend genera `state` y un par PKCE propio de TikTok (verifier de 64
caracteres, **challenge = SHA256 en hex**, `S256`) y devuelve la URL de autorización con
`user.info.basic,video.publish`. TikTok redirige el navegador al **callback de loopback del
backend** `http://127.0.0.1:8000/api/tiktok/oauth/callback` (puerto fijo registrado, configurable),
que valida estrictamente los parámetros, consume el intento, intercambia `code` + `code_verifier`
en `POST /v2/oauth/token/` (form), exige ambos scopes en la respuesta de tokens, consulta
`/v2/user/info/` y comprueba el `open_id`; el callback responde siempre `303 See Other` a la ruta
limpia `/api/tiktok/oauth/result?outcome=…` (enumerado cerrado), de modo que `code` y `state` no
quedan en la barra de direcciones ni en el historial, y el frontend conoce el resultado
consultando el intento (patrón de YouTube, Feature 005, salvo el `303`).

Access token, refresh token, caducidades (derivadas de `expires_in`/`refresh_expires_in`),
scopes y su fuente viven en **un único JSON en el keyring** (`autopublisher.tiktok`), fuente de
verdad; SQLite (`tiktok_connections`, migración `0011`) guarda solo identidad pública, estado,
referencia opaca y fechas informativas. Renovación on-demand bajo candado por cuenta: se renueva
con ≤ 1 h de vida del access token; la rotación del refresh token se aplica sobrescribiendo el
secreto completo; fallos temporales nunca llevan a `Reconnect required`. Reconnect usa una
`credential_ref` nueva y registra la anterior en `tiktok_credential_orphans` en la misma
transacción. Disconnect revoca con `POST /v2/oauth/revoke/` y distingue `revoked`,
`already_invalid`, `tiktok_revoke_failed`, `tiktok_credential_missing` y
`credential_store_unavailable`, con `remove-local` explícito. Verify separa señales vivas de
scopes conocidos. La viabilidad (Sandbox + `video.publish`) se valida en un **gate manual previo**.
Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring` (existentes).
**Sin dependencias nuevas** (PKCE con `secrets` + `hashlib`).

**Storage**: SQLite (tablas nuevas `tiktok_connections` y `tiktok_credential_orphans`, migración
`0011`); keyring del sistema (servicio `autopublisher.tiktok`); archivo local no versionado
`backend/data/tiktok-app.json`.

**Testing**: pytest con `FakeTikTok` (`httpx.MockTransport`), `InMemoryCredentialStore` y reloj
falso; Vitest + Testing Library con `FakeApi`. Sin Internet, sin TikTok, sin keyring real.

**Target Platform**: aplicación local (Linux principal) con navegador en la misma máquina que el
backend. **Supuesto explícito**: un único proceso/worker de backend (sin `--workers`); el
candado de renovación en memoria solo garantiza exclusión dentro de ese proceso; no se fingen
garantías multi-worker ni se añade infraestructura distribuida (research §11).

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: `Connected` < 10 s tras el redirect (SC-002): 2 llamadas a TikTok
(intercambio + `user/info`) con timeout de 10 s.

**Constraints**: redirect URI de loopback con puerto; PKCE hex obligatorio; cero secretos fuera
del keyring; `code`/`state` solo en la URL entrante del callback (redactada en access logs);
sin scheduler ni renovación en segundo plano; sin publishing ni `creator_info`; tests sin red.

**Scale/Scope**: un usuario y pocas cuentas; 10 rutas (incluida la ruta limpia de resultado), 2
tablas, 1 panel.

No queda ningún NEEDS CLARIFICATION: endpoints, redirect URI y puerto, PKCE, parámetros,
respuestas, scopes, identidad, renovación, rotación, revocación, errores, huérfanos,
configuración, inactivos y mecanismo de resultado del intento están resueltos en
[research.md](research.md). Lo no garantizado por la documentación se valida en el quickstart
(gate G y fases V1/V2) con condiciones de STOP.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin dependencias ni infraestructura nueva; callback en el backend existente (sin servidor temporal ni puerto aleatorio); sin renovación en segundo plano; sin publisher ni llamadas de Content Posting; registro de intentos propio en lugar de refactorizar los de otras plataformas. La tabla de huérfanos es la mínima que exige FR-034. | ✅ |
| II. Spec-Driven | Plan derivado de `spec.md` (FR-001…FR-059, FR-058a/b) incluidos los cuatro ajustes; las desviaciones del estándar (PKCE hex) proceden de la documentación oficial. | ✅ |
| III. Arquitectura modular | Módulos `tiktok_oauth.py`, `tiktok_gateway.py`, `tiktok_connections.py`. `accounts.py`, `AccountRead`, `publishing.py`, `publications.py`, `scheduler.py`, `automation.py` y los módulos de YouTube/Instagram/Threads no cambian. Tests de arquitectura ampliados a TikTok. Frontend: solo la condición por plataforma de `AccountList`. | ✅ |
| IV. Seguridad | Tokens solo en el keyring, sin fallback; client secret en archivo ignorado; `state`/verifier de un solo uso en memoria; access log del callback redactado; redacción de tokens, `code`, `state`, verifier, challenge, `client_secret`, `token` y `Bearer`; página final limpia con `no-store`; API oficial. | ✅ |
| V. Calidad | Tests de todos los casos de FR-057 con fakes; checks completos en el quickstart; ningún fallo deja estados silenciosos (Disconnect nunca afirma revocación no confirmada). | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés; README + `docs/tiktok-accounts.md`. | ✅ |

**Re-check post-diseño**: sin violaciones. No se necesita Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/012-tiktok-oauth-connection/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md          # gate G + V1 + V2
├── contracts/
│   └── api.md
├── checklists/
│   └── requirements.md
└── tasks.md               # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py                  # + get_tiktok_app_file(), TIKTOK_ATTEMPT_TTL/RETENTION,
│   │                              #   DEFAULT_TIKTOK_REDIRECT_URI, TIKTOK_CALLBACK_PATH
│   ├── credential_store.py        # + TIKTOK_SERVICE = "autopublisher.tiktok" (sin cambios de lógica)
│   ├── models.py                  # + TikTokConnection, TikTokConnectionStatus, TikTokCredentialOrphan
│   ├── schemas.py                 # + TikTokIdentityRead, TikTokPermissionsRead, TikTokConnectionRead,
│   │                              #   TikTokAuthorizeRead, TikTokOAuthAttemptRead, TikTokDisconnectRead
│   ├── tiktok_oauth.py            # NEW: TikTokAppConfig + validación del redirect URI, scopes,
│   │                              #   generate_state, generate_tiktok_pkce_pair (hex), URL de
│   │                              #   autorización, parse_callback estricto, TikTokIdentity,
│   │                              #   TikTokAttemptRegistry (memoria, estado `processing`)
│   ├── tiktok_gateway.py          # NEW: exchange_code, refresh, revoke, fetch_user_info,
│   │                              #   TikTokCredential (JSON del secreto), clasificación de errores
│   ├── tiktok_connections.py      # NEW: router, reglas, callback, confirm/cancel, verify,
│   │                              #   disconnect/remove-local, get_valid_credentials,
│   │                              #   get_linked_identity, mark_scope_not_authorized, huérfanos,
│   │                              #   RedactTikTokCallbackQuery, RedactTikTokSecrets
│   └── main.py                    # + router, registry, gateway, store, transport inyectables;
│                                  #   instalación de filtros de log; limpieza de huérfanos al arrancar
├── migrations/versions/
│   └── 0011_create_tiktok_connections.py
└── tests/
    ├── fakes.py                   # + FakeTikTok
    ├── conftest.py                # + fixtures fake_tiktok / tiktok store / tiktok app file
    ├── test_accounts.py           # arquitectura: núcleo de Accounts sin "tiktok_"
    ├── test_publications_states.py# arquitectura: publishing/scheduler/automation sin tiktok_
    ├── test_migrations.py         # + 0011
    ├── test_tiktok_oauth.py       # config/redirect URI, PKCE (vector hex), URL, parse_callback, registry
    ├── test_tiktok_gateway.py     # contrato de endpoints/form bodies, parsing, clasificación de errores
    ├── test_tiktok_connect.py     # callback happy path, scopes parciales, open_id, unicidad,
    │                              #   concurrencia, callback duplicado/tras reinicio, puerto distinto
    ├── test_tiktok_reconnect.py   # misma cuenta, cambio confirmado/cancelado/caducado, orden seguro,
    │                              #   commit fallido, borrado viejo fallido → huérfano
    ├── test_tiktok_tokens.py      # política de renovación, rotación, consistencia secreto/SQLite
    ├── test_tiktok_verify.py      # señales vivas, scopes conocidos, mismatch, access_token_invalid
    ├── test_tiktok_disconnect.py  # revoked / already_invalid / revoke_failed / credential_missing /
    │                              #   store unavailable / remove-local / idempotencia
    ├── test_tiktok_orphans.py     # registro y limpieza idempotente
    ├── test_tiktok_inactive.py    # cuentas/proyectos inactivos
    └── test_tiktok_secrets.py     # SQLite, logs (access log del callback, httpx), API, errores, form bodies

frontend/src/
├── types.ts                       # + TikTokConnection, TikTokIdentity, TikTokOAuthAttempt, TikTokDisconnect
├── api.ts                         # + funciones tiktok-connection / tiktok oauth
├── test-fake-api.ts               # + soporte TikTok
├── components/
│   ├── AccountList.tsx            # + condición platform === "tiktok"
│   ├── TikTokConnectionPanel.tsx  # NEW
│   └── TikTokConnectionPanel.test.tsx # NEW
└── storage-safety.test.tsx        # sin cambios; cubre los archivos nuevos

docs/tiktok-accounts.md            # NEW: gate, Sandbox, Login Kit Desktop, redirect URI, target user,
                                   #   config local, permisos, revocación manual
README.md                          # + "Connecting TikTok"
.gitignore                         # + tiktok-app*.json
```

**Structure Decision**: misma estructura web y mismo patrón de módulos por plataforma que las
Features 005/008/010; el flujo de callback replica el de YouTube (`youtube_connections.py`), no
el de pegar la URL de Threads.

## Diseño por capas

### `tiktok_oauth.py` (puro, sin red)

- `TikTokAppConfig(client_key, client_secret[repr=False], redirect_uri)`;
  `load_tiktok_app_config(path)` → `TikTokOAuthNotConfigured` si falta o es inválido (reglas de
  research §3).
- `SCOPES = ("user.info.basic", "video.publish")`, `REQUIRED_SCOPES = frozenset(SCOPES)`,
  `parse_scopes(str) -> frozenset[str]`.
- `generate_state()`, `generate_tiktok_pkce_pair() -> (verifier, hex_challenge)`.
- `build_authorization_url(config, state, challenge)`: solo parámetros documentados.
- `parse_callback(items) -> CallbackResult(state, code | None, error | None)` o
  `CallbackInvalid`: duplicados, `code`+`error`, ninguno, longitudes (research §6).
- `TikTokIdentity(open_id, display_name, avatar_url)` con `to_read()` y `suffix`.
- `TikTokAttemptRegistry`: interfaz de YouTube (`create`, `consume_state` → `processing` y
  devuelve el verifier una sola vez, `get`, `finish`, `await_confirmation`,
  `claim_confirmation`, `cancel`, `expire_for_account`) con descarte de credencial pendiente al
  caducar/cancelar mediante un callback de revocación best-effort inyectado.

### `tiktok_gateway.py` (solo red)

- Constantes de endpoints (research §2), `TIKTOK_TIMEOUT_SECONDS = 10`.
- `TikTokCredential` (data-model) con `to_json`/`from_json` y `requires(scopes)`.
- `exchange_code(code, verifier, config) -> TikTokCredential` (`scopes_source =
  token_exchange`), `refresh(credential, config) -> TikTokCredential` (`token_refresh`;
  usa siempre el `refresh_token` devuelto, rotado o no; si falta → `TikTokUnexpectedResponse`
  — research §7, §11),
  `revoke(access_token, config) -> None`, `fetch_user_info(access_token) -> TikTokIdentity`.
- Todas las peticiones de token/revocación con cuerpo form; ningún secreto en query.
- Excepciones de research §14, sin URL, cuerpo ni token, `from None`.

### `tiktok_connections.py` (reglas y rutas)

- Lookups: `get_tiktok_account_or_error`, `get_connection`, `oauth_configured`, `load_config`.
- Reglas: `ensure_account_connectable`, `ensure_identity_available`, `complete_connection` con
  orden seguro, `register_orphan` en la misma transacción (research §12) y traducción de la
  violación de `UNIQUE(project_id, open_id)` a `tiktok_account_already_connected` desde el primer
  flujo Connect (sin credencial parcial).
- Descarte: `discard_credential(credential)` best-effort (research §13), inyectado también en el
  registro de intentos para los cambios de cuenta cancelados o caducados.
- Callback: `_process_callback` (research §6–§8) que devuelve un `TikTokCallbackOutcome`; la
  ruta responde siempre `303` a `/api/tiktok/oauth/result?outcome=…`; la ruta de resultado
  renderiza `render_result_page(outcome)` desde un diccionario fijo, con `Cache-Control:
  no-store` y `Referrer-Policy: no-referrer` (research §6.1); comprobación de loopback en el
  callback y del puerto del socket en `authorize`.
- Ciclo de vida: `get_valid_credentials` (research §10–§11) con `REFRESH_MARGIN = 1 h`,
  `EXPIRY_MARGIN = 5 min`, candado por cuenta compartido con Verify y Disconnect; `_sync_metadata`
  idempotente; `call_with_token(fn)` aplica "una renovación + un reintento" ante
  `access_token_invalid`.
- Verify: `get_valid_credentials` → `fetch_user_info` → `open_id` → actualizar nombre, avatar,
  espejo de fechas y `last_verified_at`; nunca reescribe scopes sin renovación.
- Disconnect / remove-local: research §13; respuesta `TikTokDisconnectRead`.
- Huérfanos: `register_orphan` (usado por `complete_connection`) y `cleanup_orphans(session,
  store)` (idempotente; nunca borra una ref en uso; al arrancar y al inicio de las operaciones de
  escritura).
- `get_linked_identity`, `mark_scope_not_authorized` para la Feature 013.
- Logging: `RedactTikTokCallbackQuery` (uvicorn.access) y `RedactTikTokSecrets` (HTTP_LOGGERS),
  instalados desde `create_app`.
- Errores con `AppError(status, "tiktok_…", message)`; genéricos existentes para `not_found`,
  `platform_not_supported`, `project_inactive`, `account_inactive`,
  `credential_store_unavailable`.

### Frontend

- `TikTokConnectionPanel`: estados de spec FR-053. Connect/Reconnect: `window.open("")` síncrono
  al clic, `authorize`, navegar la pestaña a `authorization_url`, `Connecting` con enlace para
  reabrir y `Cancel`, consulta del intento cada 2 s hasta estado terminal o
  `awaiting_confirmation` (advertencia con ambas identidades, `Replace` / `Cancel`).
- `Connected`: nombre visible, avatar (marcador neutro si falta o falla), handle local,
  caducidades de acceso y de autorización renovable, `last_verified_at`, texto de permisos
  "Permissions granted according to TikTok's last authorization/renewal (date)", `Verify`,
  `Reconnect`, `Disconnect`.
- Disconnect con confirmación; mensajes distintos para `revoked`, `already_invalid`; tras
  `tiktok_revoke_failed`: `Retry` + `Remove locally without revoking`; tras
  `tiktok_credential_missing`: explicación + `Remove locally without revoking`; la eliminación
  local exige una segunda confirmación con la advertencia y el enlace a *Manage app
  permissions*.
- Nada en `localStorage`/`sessionStorage`; la `authorization_url` no se guarda en estado tras
  abrir la pestaña salvo para "reabrir" mientras dura el intento (solo memoria del componente).

## Orden de implementación (para `/speckit-tasks`)

1. **Gate G** del quickstart (manual, sin código). STOP → revisar spec.
2. Corte mínimo: config, PKCE, registry, gateway (`exchange_code`, `fetch_user_info`),
   migración, `authorize` + callback (`303` + ruta de resultado) + attempts + panel básico,
   redacción de logs → **V1**. Hasta implementar la confirmación de cambio de cuenta (US5), un
   callback con `open_id` distinto del vinculado falla de forma cerrada (sin guardar, conexión
   intacta, descarte best-effort).
   STOP si PKCE hex, redirect URI o forma de respuesta no coinciden.
3. Renovación, Verify, Reconnect + huérfanos, Disconnect/revocación/remove-local, inactivos.
4. Documentación y **V2**.

## Tests obligatorios de renovación (`test_tiktok_tokens.py`)

Con `FakeTikTok`, `InMemoryCredentialStore` y reloj falso:

1. Access con > 1 h → sin llamada a `/oauth/token/`.
2. Access con ≤ 1 h y refresh vigente → renovación; secreto con nuevo access, refresh devuelto,
   caducidades = `now + expires_in` / `now + refresh_expires_in`, scopes y
   `scopes_source = token_refresh`.
3. Access caducado y refresh vigente → renovación.
4. Refresh rotado → el secreto contiene el nuevo; una segunda renovación envía el nuevo (nunca el
   viejo).
5. Refresh no rotado → se conserva el mismo y las caducidades devueltas.
6. Fallo temporal (red, timeout, 5xx, 429, `temporarily_unavailable`) con access > 5 min →
   devuelve el actual, sin cambios; con ≤ 5 min → `tiktok_unavailable`; nunca
   `reconnect_required`.
7. `invalid_grant` → `reconnect_required`.
8. `refresh_expires_at` pasado en el secreto → `reconnect_required` sin llamar a TikTok.
9. Renovación con scopes sin `video.publish` → `reconnect_required` (`tiktok_reconnect_required`).
10. Renovación con `open_id` distinto → `tiktok_identity_mismatch` + `reconnect_required`.
11. Secreto renovado + commit SQLite fallido → devuelve la credencial nueva; secreto no
    restaurado; siguiente acceso repara el espejo sin renovar; reparación idempotente.
12. `store.set` fallido tras renovar (dos veces) → `credential_store_unavailable`, secreto
    anterior intacto, estado sin cambios.
13. Renovaciones concurrentes de la misma cuenta → una sola llamada a TikTok.
14. `invalid_client` al renovar → sin cambio de estado.
15. `GET` con espejo caducado y secreto vigente → repara; con secreto caducado/ausente →
    `reconnect_required`; almacén no disponible → sin cambio.

Tests de Disconnect (`test_tiktok_disconnect.py`) distinguen explícitamente: secreto ausente
(`tiktok_credential_missing`, sin llamadas a TikTok, nada borrado), credencial inválida según
TikTok (`already_invalid`, borrado local) y almacén inaccesible (`credential_store_unavailable`,
nada borrado).

## Riesgos y validaciones bloqueantes

| Riesgo | Mitigación |
|---|---|
| `video.publish` no autorizable en Sandbox sin App Review / exige dominio | Gate G antes de implementar; STOP (FR-058b); nunca degradar ni inventar URLs. |
| Dashboard altera o rechaza el redirect URI (barra final, host) | G-6; constante única de ruta + filtro de logs; revisar research §3. |
| TikTok rechaza el challenge hex | V-4; STOP (FR-059). |
| Forma real de token/user info distinta | V-5; tests de contrato del gateway; STOP. |
| Fallo del keyring tras una renovación con refresh rotado | Reintento único; sin fallback; riesgo de `reconnect_required` posterior documentado (research §11). |
| Semántica real de revocar un token ya revocado | V-16/V-17; ambiguo = `tiktok_revoke_failed`, nunca afirmar revocación. |
| `code`/`state` en access logs, barra de direcciones o historial | `RedactTikTokCallbackQuery` + test; callback siempre `303` a la ruta limpia de resultado; V-4 y V-19. |
| Varios workers de backend | Fuera de lo soportado (supuesto de único proceso documentado); el candado en memoria no protege entre procesos. |
| Duplicación del registro de intentos con YouTube/Threads | Aceptada para no ampliar alcance; candidato a refactor futuro. |

## Complexity Tracking

Sin violaciones de la Constitution.
